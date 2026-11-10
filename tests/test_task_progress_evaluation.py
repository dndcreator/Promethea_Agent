import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.task_progress import browser_checks, progress_summary, summarize_policies
from tests.support.runtime_efficiency import live_case
from tests.support.runtime import ScriptedModel


def test_prediction_uses_only_declared_structure_and_shares_initial_budget():
    from tests.support.task_progress import predict_output_budget, resolve_output_policy

    corpus = json.loads((Path(__file__).parent / "evaluation/budget-prediction-live.json").read_text(encoding="utf-8"))
    predicted = [resolve_output_policy(corpus["policies"][1], case, corpus["prediction"])["initial"] for case in corpus["cases"]]
    assert predicted == [2048, 4096, 8192]
    for case in corpus["cases"]:
        fixed = resolve_output_policy(corpus["policies"][1], case, corpus["prediction"])
        adaptive = resolve_output_policy(corpus["policies"][2], case, corpus["prediction"])
        assert fixed["prediction"] == adaptive["prediction"] and fixed["initial"] == adaptive["initial"]
        assert fixed["ceiling"] == fixed["initial"] and adaptive["ceiling"] == 8192
        altered = {"delivery_contract": case["delivery_contract"], "id": "different", "checks": [{"private": "anything"}], "turns": ["totally different language"]}
        assert resolve_output_policy(corpus["policies"][1], altered, corpus["prediction"]) == fixed
    assert predict_output_budget(None, corpus["prediction"])["initial"] == 8192
    with pytest.raises(ValueError):
        predict_output_budget({"fields": ["x", "x"], "actions": [], "persistent_collections": []}, corpus["prediction"])


def test_prediction_experiment_schedule_is_frozen_repeatable_and_complete():
    from scripts.evaluate_task_progress import experiment_schedule

    corpus = json.loads((Path(__file__).parent / "evaluation/budget-prediction-live.json").read_text(encoding="utf-8"))
    schedule = experiment_schedule(corpus, 2, 20261031)
    assert schedule == experiment_schedule(corpus, 2, 20261031) and len(schedule) == 18
    assert schedule != experiment_schedule(corpus, 2, 1)
    for trial in (1, 2):
        for case in corpus["cases"]:
            assert {entry["policy_id"] for entry in schedule if entry["trial"] == trial and entry["case_id"] == case["id"]} == {policy["id"] for policy in corpus["policies"]}


def test_restart_reserves_unknown_exposure_without_rewriting_prior_evidence(tmp_path):
    from scripts.evaluate_task_progress import prior_exposure

    path = tmp_path / "prior.json"
    identity, rates = {"model": "test", "endpoint_hash": "host"}, (0.3, 1.2)
    report = {"endpoint": identity, "input_output_usd_per_million": rates, "cases": [{"receipts": [
        {"usage": {"prompt_tokens": 1000, "completion_tokens": 2000}},
        {"usage": None, "max_tokens": 8192},
    ]}]}
    path.write_text(json.dumps(report), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="ceiling"):
        prior_exposure(path, identity=identity, rates=rates, input_token_cap=None)
    value = prior_exposure(path, identity=identity, rates=rates, input_token_cap=1048576)
    assert value["known_usd"] == pytest.approx(0.0027)
    assert value["unknown_reserve_usd"] == pytest.approx((1048576 * 0.3 + 8192 * 1.2) / 1_000_000)
    assert value["calls"] == 2 and value["unknown_requests"] == 1 and value["known_tokens"] == 3000
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match="same endpoint"):
        prior_exposure(path, identity={"model": "other"}, rates=rates, input_token_cap=1048576)


@pytest.mark.asyncio
async def test_timeout_receipt_retains_bounded_input_and_does_not_retry(monkeypatch):
    import openai
    from tests.support.evaluation import Budget
    from tests.support.runtime_efficiency import PairedEndpoint

    options, sent = {}, []

    async def transport(**kwargs):
        sent.append(kwargs)
        raise TimeoutError("simulated")

    def client(**kwargs):
        options.update(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=transport)))

    monkeypatch.setattr(openai, "AsyncOpenAI", client)
    endpoint = PairedEndpoint({"PROMETHEA_EVAL_AGENT_MODEL": "test", "PROMETHEA_EVAL_AGENT_BASE_URL": "https://example.invalid", "PROMETHEA_EVAL_AGENT_API_KEY": "fake"},
                              Budget(max_tokens=10000, max_cost_usd=0.1), (0.3, 1.2), request_timeout=120)
    with pytest.raises(RuntimeError, match="TimeoutError"):
        await endpoint.call_llm([{"role": "user", "content": "\u4e2d\u6587"}], user_config={"api": {"max_tokens": 2048}})
    assert len(sent) == 1 and options["max_retries"] == 0 and options["timeout"] == 120
    assert not endpoint.budget.usage_known and endpoint.receipts[0]["usage"] is None
    assert endpoint.receipts[0]["input_bytes"] > endpoint.receipts[0]["input_chars"]


@pytest.mark.asyncio
async def test_all_prediction_arms_receive_same_contract_without_private_checks_or_extra_model_calls(tmp_path, monkeypatch):
    from tests.support import task_progress

    async def grade(html, checks):
        return {"functional": {"passed": html == "verified"}}

    monkeypatch.setattr(task_progress, "browser_checks", grade)
    corpus = json.loads((Path(__file__).parent / "evaluation/budget-prediction-live.json").read_text(encoding="utf-8"))
    case = {"id": "test", "kind": "action", "artifact": "app.html", "checks": [{"id": "functional", "private": "PRIVATE-ORACLE-29"}],
            "delivery_contract": corpus["cases"][0]["delivery_contract"], "turns": ["Create app.html"], "expect": {}}
    requests = []
    for policy in corpus["policies"]:
        class Endpoint(ScriptedModel):
            model = "scripted"

            def __init__(self):
                super().__init__([{"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "app.html", "content": "verified"}},
                                  {"action": "answer", "content": "Delivered."}])
                self.receipts, self.limits = [], []

            async def call_llm(self, *args, **kwargs):
                self.limits.append(kwargs["user_config"]["api"]["max_tokens"])
                result = await super().call_llm(*args, **kwargs)
                self.receipts.append({"usage": result["usage"]})
                return result

        endpoint = Endpoint()
        effective = task_progress.resolve_output_policy(policy, case, corpus["prediction"])
        row = await live_case(case, endpoint, tmp_path / policy["id"], policy["id"], policy={**effective, "max_steps": 8})
        assert row["delivered"] and len(endpoint.calls) == 2
        assert endpoint.limits == [effective["initial"]] * 2
        prompt = next(message["content"] for message in endpoint.calls[0] if isinstance(message.get("content"), str) and "Structured delivery requirements:" in message["content"])
        assert "PRIVATE-ORACLE-29" not in json.dumps(endpoint.calls)
        requests.append(prompt)
    assert requests[0] == requests[1] == requests[2]


def test_historical_audit_correlates_committed_writes_not_model_claims(tmp_path):
    from scripts.evaluate_task_progress import audit_previous
    from tests.support.evaluation import digest

    root = tmp_path / "trial-1/case/fixed"
    files = root / "workspaces/alice/evaluation"
    files.mkdir(parents=True)
    (files / "app.html").write_text("actual code", encoding="utf-8")
    events = [
        {"event_type": "model.call.recorded", "payload": {"model_step_id": "one"}},
        {"event_type": "model.call.recorded", "payload": {"model_step_id": "two"}},
        {"event_type": "action.observation.committed", "payload": {"model_step_id": "two", "tool_name": "workspace.write_file", "ok": True}},
        {"event_type": "model.call.recorded", "payload": {"model_step_id": "three"}},
    ]
    (root / "events.jsonl").write_text("\n".join(json.dumps(row) for row in events), encoding="utf-8")
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"fully_paired_cases": [[1, "case"]], "cases": [{"trial": 1, "id": "case", "condition": "fixed", "delivered": True,
                           "calls": 3, "observation_errors": [], "artifact_hashes": {"app.html": digest("actual code")}}]}), encoding="utf-8")
    row = audit_previous(path)["rows"][0]
    assert row["first_successful_write_call"] == 2 and row["calls_after_last_successful_write"] == 1
    assert row["retained_code_artifacts"][0]["matches_original_receipt"]


def snapshot(call, passed, all_passed=False):
    return {"call": call, "passed_checks": passed, "failed_checks": [] if all_passed else ["remaining"], "all_passed": all_passed}


def test_more_calls_or_text_do_not_create_progress_and_later_regression_is_retained():
    rows = [snapshot(0, []), snapshot(1, []), snapshot(2, ["ui"]), snapshot(3, ["ui"]),
            snapshot(4, ["ui", "behavior"], True), snapshot(5, ["ui"])]
    result = progress_summary(rows, 7)
    assert not result["goal_met"]
    assert result["first_delivery_call"] == 4
    assert result["new_checks_ever_passed"] == ["behavior", "ui"]
    assert result["regressions"] == [{"call": 5, "checks": ["behavior"]}]
    assert result["calls_after_last_check_gain"] == 3
    assert len(result["advances"]) == 2


def test_incomplete_three_arm_group_is_excluded_not_scored_as_agent_failure():
    policies = [{"id": key} for key in ("fixed_small", "fixed_large", "adaptive")]
    rows = []
    for trial in (1, 2):
        for policy in policies:
            progress = progress_summary([snapshot(0, []), snapshot(2, ["ui"], True)], 3)
            rows.append({"trial": trial, "id": "case", "condition": policy["id"], "evaluation_complete": not (trial == 2 and policy["id"] == "adaptive"),
                         "progress": progress, "delivered": True, "calls": 3, "conservative_cost_usd": 0.01, "observation_errors": []})
    result = summarize_policies(rows, policies)
    assert result["comparable_groups"] == [(1, "case")]
    assert all(row["comparable_trials"] == row["functional_goals_met"] == 1 for row in result["policies"].values())


@pytest.mark.asyncio
async def test_progress_experiment_stops_before_transport_when_admission_is_insufficient(tmp_path, monkeypatch):
    import openai
    from scripts.evaluate_task_progress import run_live
    from tests.support import task_progress

    sent = []

    async def transport(**kwargs):
        sent.append(kwargs)
        raise AssertionError("No paid request may pass admission")

    async def close():
        pass

    async def grade(html, checks):
        return {check["id"]: {"passed": check["id"] == "ready"} for check in checks}

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=transport)), close=close))
    monkeypatch.setattr(task_progress, "browser_checks", grade)
    env = tmp_path / ".env.eval"
    env.write_text("\n".join([
        "PROMETHEA_EVAL_AGENT_BASE_URL=https://example.invalid/v1", "PROMETHEA_EVAL_AGENT_API_KEY=not-a-key",
        "PROMETHEA_EVAL_AGENT_MODEL=test", "PROMETHEA_EVAL_AGENT_INPUT_USD_PER_MILLION=0.3",
        "PROMETHEA_EVAL_AGENT_OUTPUT_USD_PER_MILLION=1.2", "PROMETHEA_EVAL_MAX_COST_USD=0.1",
    ]), encoding="utf-8")
    report = await run_live(tmp_path / "result", env, 0.000000001, 1)
    assert sent == [] and report["model_api_calls"] == 0 and report["conservative_cost_usd"] == 0
    assert report["summary"]["comparable_groups"] == [] and report["stop_reason"]
    assert len(report["cases"]) == 1 and not report["cases"][0]["evaluation_complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("write", [True, False])
async def test_runtime_artifact_changes_not_assistant_claims_determine_delivery(tmp_path, monkeypatch, write):
    from tests.support import task_progress

    async def grade(html, checks):
        return {"functional": {"passed": html == "verified"}}

    monkeypatch.setattr(task_progress, "browser_checks", grade)

    class Endpoint(ScriptedModel):
        model = "scripted-not-a-real-model"

        def __init__(self, actions):
            super().__init__(actions)
            self.receipts = []

        async def call_llm(self, *args, **kwargs):
            response = await super().call_llm(*args, **kwargs)
            self.receipts.append({"usage": response.get("usage")})
            return response

    actions = [
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "app.html", "content": "broken"}},
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "app.html", "content": "verified"}},
    ] if write else []
    actions.append({"action": "answer", "content": "All code has been delivered and tested."})
    case = {"id": "test", "kind": "action", "artifact": "app.html", "checks": [{"id": "functional"}],
            "turns": ["Create app.html"], "expect": {}}
    row = await live_case(case, Endpoint(actions), tmp_path, "adaptive", policy={"initial": 2000, "ceiling": 8192, "max_steps": 5})
    assert row["progress"]["goal_met"] is write
    assert row["delivered"] is write
    assert row["progress"]["initial_passed"] == []
    if write:
        assert row["progress"]["first_delivery_call"] == 2
        assert len(list((tmp_path / "artifact-versions").glob("*.html"))) == 2
    else:
        assert row["progress"]["advances"] == []


REFERENCE_CALCULATOR = """<!doctype html><input id=a type=number><input id=b type=number><button id=calculate>Add</button><output id=result></output>
<script>document.querySelector('#calculate').onclick=()=>{const a=document.querySelector('#a').value,b=document.querySelector('#b').value;document.querySelector('#result').textContent=a.trim()===''||b.trim()===''?'Invalid':Number(a)+Number(b)}</script>"""

REFERENCE_QUOTATION = """<!doctype html><input id=quantity type=number><input id=price type=number><input id=discount type=number><input id=tax type=number><button id=calculate>Calculate</button><output id=total></output>
<script>document.querySelector('#calculate').onclick=()=>{const raw=['quantity','price','discount','tax'].map(id=>document.getElementById(id).value);const [q,p,d,t]=raw.map(Number);document.getElementById('total').textContent=raw.some(x=>!x.trim())||![q,p,d,t].every(Number.isFinite)||q<0||p<0||d<0||d>100||t<0?'Invalid':(q*p*(1-d/100)*(1+t/100)).toFixed(2)}</script>"""

REFERENCE_TODO = """<!doctype html><input id=new-task><button id=add-task>Add</button><ul id=tasks></ul><script>
let items=JSON.parse(localStorage.getItem('tasks')||'[]');function save(){localStorage.setItem('tasks',JSON.stringify(items))}
function render(){const list=document.getElementById('tasks');list.replaceChildren();items.forEach((item,i)=>{const li=document.createElement('li'),title=document.createElement('span'),check=document.createElement('input'),remove=document.createElement('button');title.className='task-title';title.textContent=item.title;check.type='checkbox';check.checked=item.done;check.onchange=()=>{item.done=check.checked;save()};remove.textContent='Delete';remove.onclick=()=>{items.splice(i,1);save();render()};li.append(title,check,remove);list.append(li)})}
document.getElementById('add-task').onclick=()=>{const input=document.getElementById('new-task');if(!input.value.trim())return;items.push({title:input.value.trim(),done:false});input.value='';save();render()};render();</script>"""


REFERENCE_SCRATCHPAD = """<!doctype html><textarea id=note></textarea><output id=count>0</output><button id=clear>Clear</button><script>
const note=document.getElementById('note'),count=document.getElementById('count');note.oninput=()=>count.textContent=Array.from(note.value).length;document.getElementById('clear').onclick=()=>{note.value='';count.textContent='0'};</script>"""

REFERENCE_SPLITTER = """<!doctype html><input id=amount type=number><input id=people type=number><input id=tip type=number><button id=calculate>Calculate</button><output id=grand></output><output id=share></output><script>
document.getElementById('calculate').onclick=()=>{const raw=['amount','people','tip'].map(id=>document.getElementById(id).value),[a,p,t]=raw.map(Number);const bad=raw.some(x=>!x.trim())||![a,p,t].every(Number.isFinite)||a<0||p<=0||!Number.isInteger(p)||t<0||t>100;document.getElementById('grand').textContent=bad?'Invalid':(a*(1+t/100)).toFixed(2);document.getElementById('share').textContent=bad?'Invalid':(a*(1+t/100)/p).toFixed(2)};</script>"""

REFERENCE_INVENTORY = """<!doctype html><input id=sku><input id=qty type=number><input id=price type=number><button id=add>Add</button><input id=filter><ul id=items></ul><output id=error></output><output id=count></output><output id=total></output><script>
const by=id=>document.getElementById(id);let data=JSON.parse(localStorage.getItem('inventory')||'[]');function save(){localStorage.setItem('inventory',JSON.stringify(data))}function totals(){by('count').textContent=data.length;by('total').textContent=data.reduce((s,x)=>s+x.qty*x.price,0).toFixed(2)}
function render(){by('items').replaceChildren();data.forEach((x,i)=>{if(!x.sku.toLowerCase().includes(by('filter').value.toLowerCase()))return;const li=document.createElement('li'),sku=document.createElement('span'),qty=document.createElement('input'),price=document.createElement('span'),remove=document.createElement('button');sku.className='sku';sku.textContent=x.sku;qty.className='quantity';qty.type='number';qty.value=x.qty;qty.oninput=()=>{const n=Number(qty.value);if(qty.value.trim()&&Number.isInteger(n)&&n>=0){x.qty=n;save();totals()}};price.className='unit-price';price.textContent=x.price;remove.className='remove';remove.textContent='Remove';remove.onclick=()=>{data.splice(i,1);save();render()};li.append(sku,qty,price,remove);by('items').append(li)});totals()}
by('add').onclick=()=>{const sku=by('sku').value.trim(),q=by('qty').value,p=by('price').value,qty=Number(q),price=Number(p);if(!sku||!q.trim()||!p.trim()||!Number.isInteger(qty)||qty<0||!Number.isFinite(price)||price<0||data.some(x=>x.sku===sku)){by('error').textContent='Invalid';return}data.push({sku,qty,price});by('error').textContent='';save();render()};by('filter').oninput=render;render();</script>"""


@pytest.mark.browser
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser evaluator")
async def test_prediction_task_oracles_accept_reference_and_reject_broken_deliveries():
    cases = json.loads((Path(__file__).parent / "evaluation/budget-prediction-live.json").read_text(encoding="utf-8"))["cases"]
    references = {"unicode-scratchpad": REFERENCE_SCRATCHPAD, "bill-splitter": REFERENCE_SPLITTER, "persistent-inventory": REFERENCE_INVENTORY}
    for case in cases:
        result = await browser_checks(references[case["id"]], case["checks"])
        assert all(row["passed"] for row in result.values()), (case["id"], result)
        prose = await browser_checks('<p>Everything is done.</p>', case["checks"][:1])
        assert not all(row["passed"] for row in prose.values())
    broken = await browser_checks(REFERENCE_SCRATCHPAD.replace('Array.from(note.value).length', 'note.value.length'), cases[0]["checks"])
    assert not broken["unicode-count"]["passed"] and broken["live-edit"]["passed"]
    broken = await browser_checks(REFERENCE_INVENTORY.replace("localStorage.setItem('inventory',JSON.stringify(data))", "void 0"), cases[2]["checks"])
    assert not broken["add-and-reload"]["passed"] and broken["duplicate"]["passed"]


@pytest.mark.browser
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser evaluator")
async def test_browser_oracles_accept_reference_code_and_reject_broken_code_and_prose():
    cases = json.loads((Path(__file__).parent / "evaluation/task-progress-live.json").read_text(encoding="utf-8"))["cases"]
    references = {"repair-calculator": REFERENCE_CALCULATOR, "quotation-ui": REFERENCE_QUOTATION, "persistent-todo": REFERENCE_TODO}
    assert {case["id"] for case in cases} == set(references)
    for case in cases:
        html = references[case["id"]]
        result = await browser_checks(html, case["checks"])
        assert all(row["passed"] for row in result.values()), (case["id"], result)
    broken = REFERENCE_CALCULATOR.replace('Number(a)+Number(b)', 'a+b')
    result = await browser_checks(broken, cases[0]["checks"])
    assert result["interface"]["passed"]
    assert not result["integer-sum"]["passed"] and not result["negative-decimal"]["passed"]
    prose = await browser_checks('<p>I completed the calculator.</p>', cases[0]["checks"][:1])
    assert not prose["interface"]["passed"]
