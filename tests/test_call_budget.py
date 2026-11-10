from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from gateway.action.model_action import InvalidModelAction, parse_model_action
from tests.support.call_budget import allowance_changes, call_allowance, response_contract, validate_response_contract, call_budget_case
from tests.support.runtime import ScriptedModel
from tests.support.task_progress import browser_checks, resolve_output_policy


CORPUS = Path(__file__).parent / "evaluation/call-budget-live.json"


class RecordingModel(ScriptedModel):
    model = "scripted"
    def __init__(self, actions):
        super().__init__(actions)
        self.receipts = []

    async def call_llm(self, *args, **kwargs):
        config = kwargs["user_config"]
        result = await super().call_llm(*args, **kwargs)
        self.receipts.append({"max_tokens": config["api"]["max_tokens"], "usage": result.get("usage"),
                              "code": result.get("code"),
                              "purpose": config["_runtime_call"]["purpose"], "output_budget": deepcopy(config["_eval_output_budget"])})
        return result


def corpus():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def test_pilot_registration_is_new_balanced_and_does_not_retune_legacy_prior():
    from scripts.evaluate_task_progress import experiment_schedule
    config = corpus()
    old = json.loads(CORPUS.with_name("budget-independent-live.json").read_text(encoding="utf-8"))
    assert not {case["id"] for case in config["cases"]} & {case["id"] for case in old["cases"]}
    assert config["prediction"] == old["prediction"]
    assert len(experiment_schedule(config, 2, 20261102)) == 18
    assert [resolve_output_policy(config["policies"][1], case, config["prediction"])["initial"] for case in config["cases"]] == [2048, 4096, 2048]
    assert config["registration"]["provider_thinking"] == "unchanged_default"


def test_unknown_and_answer_only_are_not_assumed_short():
    assert call_allowance(None)["initial"] == 8192
    assert call_allowance({"max_action_chars": True})["initial"] == 8192
    assert call_allowance({"max_action_chars": 20000})["initial"] == 8192
    flow = corpus()["cases"][0]["runtime_output_flow"]
    assert response_contract(flow, [], final_answer=True) is None
    assert call_allowance(response_contract(flow, []))["initial"] == 4096


def test_only_committed_read_changes_the_response_contract():
    flow = corpus()["cases"][-1]["runtime_output_flow"]
    claim = [{"kind": "answer", "ok": True, **flow["read"]}]
    assert response_contract(flow, claim) is not None
    failed = [{"kind": "tool_call", "ok": False, **flow["read"]}]
    assert response_contract(flow, failed) is not None
    success = [{"kind": "tool_call", "ok": True, **flow["read"]}]
    assert response_contract(flow, success) is None


def test_runtime_contract_rejects_other_calls_and_unbounded_metadata():
    flow = corpus()["cases"][0]["runtime_output_flow"]
    contract = response_contract(flow, [])
    read = {"action": "tool_call", **flow["read"]}
    validate_response_contract(parse_model_action(json.dumps(read)), contract)
    for invalid in [{"action": "tool_call", "tool_name": "workspace.write_file", "args": {}},
                    {**read, "gap_update": {"note": "x" * 2000}}, {"action": "answer", "content": "I have read it"}]:
        with pytest.raises(InvalidModelAction):
            validate_response_contract(parse_model_action(json.dumps(invalid)), contract)
    contract = response_contract(flow, [{"kind": "tool_call", "ok": True, **flow["read"]}])
    validate_response_contract(parse_model_action(json.dumps({"action": "answer", "content": json.dumps(corpus()["cases"][0]["expect"]["answer_json"])})), contract)
    with pytest.raises(InvalidModelAction):
        validate_response_contract(parse_model_action(json.dumps({"action": "answer", "content": '{"A":"unsupported"}'})), contract)


def test_scope_widening_is_not_mislabeled_as_truncation_recovery():
    receipts = [{"max_tokens": 4096, "code": "MODEL_OUTPUT_LIMIT", "output_budget": {"contract_hash": "read"}},
                {"max_tokens": 8192, "output_budget": {"contract_hash": "read"}},
                {"max_tokens": 4096, "output_budget": {"contract_hash": "answer"}},
                {"max_tokens": 8192, "output_budget": {"contract_hash": "free"}}]
    assert [change["reason"] for change in allowance_changes(receipts)] == ["real_truncation_recovery", "runtime_output_scope_changed", "runtime_output_scope_changed"]


@pytest.mark.asyncio
async def test_three_arms_share_phase_contracts_but_only_candidate_changes_per_call(tmp_path, monkeypatch):
    from tests.support import task_progress
    async def grade(html, checks):
        return {"functional": {"passed": html == "verified"}}
    monkeypatch.setattr(task_progress, "browser_checks", grade)
    config = corpus()
    case = deepcopy(config["cases"][-1])
    case["checks"] = [{"id": "functional", "private": "PRIVATE-ORACLE-62"}]
    observed, instructions = [], []
    for policy in config["policies"]:
        endpoint = RecordingModel([{"action": "tool_call", **case["runtime_output_flow"]["read"]},
                                   {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": case["artifact"], "content": "verified"}},
                                   {"action": "answer", "content": "Delivered"}])
        effective = resolve_output_policy(policy, case, config["prediction"])
        row = await call_budget_case(case, endpoint, tmp_path / policy["id"], policy["id"], policy={**effective, "max_steps": 6})
        assert row["delivered"], row["failures"]
        observed.append([receipt["max_tokens"] for receipt in endpoint.receipts])
        assert len(endpoint.calls) == 3 and "PRIVATE-ORACLE-62" not in json.dumps(endpoint.calls)
        instructions.append(next(message["content"] for message in endpoint.calls[0] if str(message.get("content", "")).startswith("Current Runtime response contract")))
    assert observed == [[8192] * 3, [2048] * 3, [4096, 8192, 8192]]
    assert len(set(instructions)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error,limits", [("MODEL_OUTPUT_LIMIT", [4096, 8192, 4096]), ("INVALID_JSON", [4096, 4096, 4096])])
async def test_only_actual_truncation_grows_and_new_output_scope_resets_allowance(tmp_path, error, limits):
    config = corpus()
    case = config["cases"][0]
    bad = {"status": "error", "code": error, "content": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0}} if error == "MODEL_OUTPUT_LIMIT" else "not JSON"
    endpoint = RecordingModel([bad, {"action": "tool_call", **case["runtime_output_flow"]["read"]},
                               {"action": "answer", "content": json.dumps(case["expect"]["answer_json"])}])
    row = await call_budget_case(case, endpoint, tmp_path, "input_output_aware", policy={"initial": 8192, "ceiling": 8192, "call_aware": True, "max_steps": 6})
    assert row["delivered"], row["failures"]
    assert [receipt["max_tokens"] for receipt in endpoint.receipts] == limits
    assert row["progress"]["goal_met"]


@pytest.mark.asyncio
async def test_allowed_but_wrong_finite_answer_fails_independent_gold(tmp_path):
    case = corpus()["cases"][0]
    endpoint = RecordingModel([{"action": "tool_call", **case["runtime_output_flow"]["read"]},
                               {"action": "answer", "content": json.dumps({key: "ready" for key in case["expect"]["answer_json"]})}])
    row = await call_budget_case(case, endpoint, tmp_path, "input_output_aware", policy={"initial": 8192, "ceiling": 8192, "call_aware": True, "max_steps": 6})
    assert not row["delivered"] and "answer_json_mismatch" in row["failures"]
    assert not row["progress"]["goal_met"]


@pytest.mark.asyncio
async def test_final_answer_only_does_not_reduce_unknown_report_allowance(tmp_path):
    case = deepcopy(corpus()["cases"][-1])
    case.pop("checks")
    endpoint = RecordingModel([{"action": "tool_call", **case["runtime_output_flow"]["read"]},
                               {"action": "answer", "content": "Not delivered; the execution slice ended after reading."}])
    row = await call_budget_case(case, endpoint, tmp_path, "input_output_aware", policy={"initial": 8192, "ceiling": 8192, "call_aware": True, "max_steps": 1})
    assert not row["delivered"]
    assert [receipt["max_tokens"] for receipt in endpoint.receipts] == [4096, 8192]
    assert endpoint.receipts[-1]["output_budget"]["final_answer_only"] is True


@pytest.mark.asyncio
async def test_live_runner_budget_stops_before_any_send(tmp_path, monkeypatch):
    import openai
    from types import SimpleNamespace
    from tests.support import task_progress
    from scripts.evaluate_call_budget import run
    async def no_send(**kwargs):
        raise AssertionError("no admission means no API request")
    async def close():
        pass
    async def canary(*args):
        return {"ready": {"passed": True}}
    monkeypatch.setattr(task_progress, "browser_checks", canary)
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=no_send)), close=close))
    env = tmp_path / ".env.eval"
    env.write_text("\n".join(["PROMETHEA_EVAL_AGENT_BASE_URL=https://example.invalid", "PROMETHEA_EVAL_AGENT_API_KEY=fake", "PROMETHEA_EVAL_AGENT_MODEL=fixture", "PROMETHEA_EVAL_AGENT_INPUT_USD_PER_MILLION=0.3", "PROMETHEA_EVAL_AGENT_OUTPUT_USD_PER_MILLION=1.2", "PROMETHEA_EVAL_MAX_COST_USD=0.30"]), encoding="utf-8")
    report = await run(tmp_path / "result", env, 0.000000001)
    assert report["model_api_calls"] == 0 and report["stop_reason"]
    assert not report["summary"]["comparable_groups"]


REFERENCE_INVOICE = '''<!doctype html><input id="price"><input id="quantity"><input id="discount"><button id="calculate">Calculate</button><button id="reset">Reset</button><output id="result"></output><output id="error"></output><script>
const get=id=>document.getElementById(id);get('calculate').onclick=()=>{let p=get('price').value,q=get('quantity').value,d=get('discount').value;const fail=()=>{get('result').textContent='';get('error').textContent='Invalid'};if(!/^\\d+(?:\\.\\d{1,2})?$/.test(p)||!/^\\d+$/.test(q)||!/^\\d+$/.test(d)||Number(q)>1000||Number(d)>100)return fail();const parts=p.split('.'),cents=Number(parts[0])*100+Number((parts[1]||'').padEnd(2,'0'));const total=Math.floor((cents*Number(q)*(100-Number(d))+50)/100);get('result').textContent=(total/100).toFixed(2);get('error').textContent=''};get('reset').onclick=()=>{for(const id of ['price','quantity','discount'])get(id).value='';get('result').textContent='';get('error').textContent=''};</script>'''
REFERENCE_LINKS = '''<!doctype html><input id="base" value="https://example.com/folder/"><textarea id="urls"></textarea><button id="normalize">Normalize</button><pre id="result"></pre><output id="error"></output><script>
const get=id=>document.getElementById(id);get('normalize').onclick=()=>{try{const safe=u=>{if(!['https:','http:'].includes(u.protocol)||u.username||u.password)throw Error('invalid');return u.href};const base=safe(new URL(get('base').value));const result=[];for(const line of get('urls').value.split(/\\r?\\n/)){if(!line.trim())continue;const url=safe(new URL(line.trim(),base));if(!result.includes(url))result.push(url)}get('result').textContent=JSON.stringify(result);get('error').textContent=''}catch(e){get('result').textContent='';get('error').textContent='Invalid'}};</script>'''


@pytest.mark.browser
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in independent browser oracle calibration")
async def test_new_browser_oracles_reject_wrong_math_unsafe_urls_and_prose():
    cases = corpus()["cases"][1:]
    for case, html in zip(cases, [REFERENCE_INVOICE, REFERENCE_LINKS]):
        results = await browser_checks(html, case["checks"])
        assert all(row["passed"] for row in results.values()), (case["id"], results)
        prose = await browser_checks("<p>All work completed.</p>", case["checks"][:1])
        assert not next(iter(prose.values()))["passed"]
    broken = REFERENCE_INVOICE.replace("+50", "+0")
    result = await browser_checks(broken, [check for check in cases[0]["checks"] if check["id"] == "half-cent"])
    assert not result["half-cent"]["passed"]
    broken = REFERENCE_LINKS.replace("||u.username||u.password", "")
    result = await browser_checks(broken, [check for check in cases[1]["checks"] if check["id"] == "reject-credentials"])
    assert not result["reject-credentials"]["passed"]
