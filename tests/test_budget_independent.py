import json
import os
from pathlib import Path

import pytest

from scripts.evaluate_task_progress import experiment_schedule
from tests.support.task_progress import browser_checks, resolve_output_policy


CORPUS = Path(__file__).parent / "evaluation/budget-independent-live.json"
REFERENCES = [
    '''<input id="height" type="number"><input id="weight" type="number"><button id="calculate">Go</button><output id="result"></output><output id="error"></output><script>
calculate.onclick=()=>{let h=Number(height.value),w=Number(weight.value);if(!height.value||!weight.value||h<=0||w<=0){result.textContent='';error.textContent='Invalid'}else{result.textContent=(w/(h/100)**2).toFixed(2);error.textContent=''}};</script>''',
    '''<input id="initial" type="number"><input id="monthly" type="number"><input id="months" type="number"><input id="annual" type="number"><button id="calculate">Go</button><output id="result"></output><output id="error"></output><script>
calculate.onclick=()=>{let inputs=[initial,monthly,months,annual],v=inputs.map(x=>Number(x.value));if(inputs.some(x=>!x.value)||v.some(x=>!Number.isFinite(x)||x<0)||!Number.isInteger(v[2])||v[2]>600){result.textContent='';error.textContent='Invalid';return}let amount=v[0];for(let i=0;i<v[2];i++)amount=amount*(1+v[3]/1200)+v[1];result.textContent=amount.toFixed(2);error.textContent=''};</script>''',
    '''<input id="name"><input id="email"><input id="query"><button id="add">Add</button><button id="export">Export</button><button id="reset">Reset</button><output id="count"></output><pre id="result"></pre><output id="error"></output><ul id="rows"></ul><script>
const n=document.getElementById('name'),e=document.getElementById('email');let data=JSON.parse(localStorage.getItem('contacts')||'[]');
function render(){count.textContent=data.length;rows.replaceChildren();data.forEach((item,index)=>{if(!(item.name+' '+item.email).toLowerCase().includes(query.value.toLowerCase()))return;let li=document.createElement('li'),b=document.createElement('button');li.append(document.createTextNode(item.name+' '+item.email));b.className='delete';b.textContent='Delete';b.onclick=()=>{data.splice(index,1);save()};li.append(b);rows.append(li)})}
function save(){localStorage.setItem('contacts',JSON.stringify(data));render()}
add.onclick=()=>{let name=n.value.trim(),email=e.value.trim();if(!name||!email.includes('@')||data.some(x=>x.email.toLowerCase()===email.toLowerCase())){error.textContent='Invalid';return}data.push({name,email});error.textContent='';save()};
query.oninput=render;document.getElementById('export').onclick=()=>result.textContent=JSON.stringify(data);reset.onclick=()=>{data=[];query.value='';result.textContent='';error.textContent='';save()};render();</script>''',
    '''<textarea id="base"></textarea><textarea id="patch"></textarea><button id="merge">Merge</button><pre id="result"></pre><output id="error"></output><script>
function object(x){return x!==null&&typeof x==='object'&&!Array.isArray(x)}
function apply(b,p){if(!object(p))return p;const out=Object.assign(Object.create(null),object(b)?b:{});for(const key of Object.keys(p)){if(p[key]===null)delete out[key];else out[key]=apply(out[key],p[key])}return out}
merge.onclick=()=>{try{result.textContent=JSON.stringify(apply(JSON.parse(base.value),JSON.parse(patch.value)));error.textContent=''}catch(e){result.textContent='';error.textContent='Invalid'}};</script>''',
]


def test_new_corpus_is_disjoint_and_policies_are_frozen():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    old = json.loads(CORPUS.with_name("budget-four-category-live.json").read_text(encoding="utf-8"))
    assert not {row["id"] for row in corpus["cases"]} & {row["id"] for row in old["cases"]}
    assert len(experiment_schedule(corpus, 2, 20261101)) == 24
    assert [resolve_output_policy(corpus["policies"][1], row, corpus["prediction"])["initial"] for row in corpus["cases"]] == [2048, 4096, 8192, 2048]
    for row in corpus["cases"]:
        b, c = [resolve_output_policy(policy, row, corpus["prediction"]) for policy in corpus["policies"][1:]]
        assert b["initial"] == c["initial"]
    assert corpus["registration"]["protocol"] == "prompt_json"


def test_decision_accounting_does_not_guess_reasoning_and_proposals_are_not_commits():
    from tests.support.task_progress import decision_summary, decision_trace
    summary = decision_summary('{"action":"tool_call","tool_name":"workspace.write_file","args":{}}', {"completion_tokens": 100, "completion_tokens_details": {"reasoning_tokens": 80}}, "length")
    assert summary["reasoning_tokens"] == 80 and summary["non_reasoning_completion_tokens"] == 20
    assert summary["truncation_region"] == "complete_action_not_accepted"
    assert decision_summary("", {"completion_tokens": 100}, "length")["reasoning_tokens"] is None
    assert decision_summary('{"action":', {}, "length")["truncation_region"] == "incomplete_action_text"
    rows = decision_trace([{"max_tokens": 8192, "decision": summary}], [{"model_step_id": "s"}],
                          [{"model_step_id": "s", "tool_name": "runtime.model_response", "ok": False, "error": {"code": "MODEL_OUTPUT_LIMIT"}}], None)
    assert rows[0]["successful_file_commits"] == 0 and rows[0]["proposal"]["tools"][0]["name"] == "workspace.write_file"


@pytest.mark.browser
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in browser calibration")
async def test_new_oracles_pass_reference_and_reject_prose():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    for case, reference in zip(corpus["cases"], REFERENCES):
        result = await browser_checks(reference, case["checks"])
        assert all(row["passed"] for row in result.values()), (case["id"], result)
        result = await browser_checks("<p>Everything is completed.</p>", case["checks"][:1])
        assert not next(iter(result.values()))["passed"]


@pytest.mark.browser
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in browser calibration")
async def test_new_oracles_reject_semantic_defects():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    mutants = [REFERENCES[0].replace("h/100", "h"), REFERENCES[1].replace("amount*(1+v[3]/1200)+v[1]", "(amount+v[1])*(1+v[3]/1200)"),
               REFERENCES[2].replace("localStorage.setItem('contacts',JSON.stringify(data));", ""),
               REFERENCES[3].replace("if(p[key]===null)delete out[key]", "if(p[key]===null)out[key]=null")]
    ids = ["bmi", "interest-order", "persist-and-export", "nested-delete"]
    for case, html, identifier in zip(corpus["cases"], mutants, ids):
        result = await browser_checks(html, [row for row in case["checks"] if row["id"] == identifier])
        assert not result[identifier]["passed"]
