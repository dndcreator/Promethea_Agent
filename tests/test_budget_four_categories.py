import json
import os
from pathlib import Path

import pytest

from tests.support.task_progress import browser_checks, resolve_output_policy
from tests.test_task_progress_evaluation import REFERENCE_SCRATCHPAD, REFERENCE_SPLITTER, REFERENCE_INVENTORY


CORPUS = Path(__file__).parent / "evaluation/budget-four-category-live.json"


REFERENCE_CSV = r'''<!doctype html><textarea id="csv"></textarea><button id="calculate">Calculate</button><pre id="result"></pre><output id="error"></output><script>
function parseCSV(text){
 const rows=[];let row=[],field='',state=0;
 function endField(){row.push(field);field='';state=0}
 function endRow(){endField();if(row.some(x=>x.trim()!==''))rows.push(row);row=[]}
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(state===1){if(c==='"'){if(text[i+1]==='"'){field+='"';i++}else state=2}else field+=c;continue}
  if(c===','){endField();continue}
  if(c==='\n'||c==='\r'){if(c==='\r'){if(text[i+1]!=='\n')throw Error('CR');i++}endRow();continue}
  if(state===2)throw Error('after quote');
  if(c==='"'){if(field!=='')throw Error('quote');state=1}else field+=c;
 }
 if(state===1)throw Error('unclosed');endRow();return rows;
}
document.getElementById('calculate').onclick=()=>{
 const output=document.getElementById('result'),error=document.getElementById('error');
 try{
  const rows=parseCSV(document.getElementById('csv').value);
  if(!rows.length||JSON.stringify(rows.shift())!==JSON.stringify(['sku','quantity','price']))throw Error('header');
  const map=new Map();let total=0;
  for(const row of rows){
   if(row.length!==3)throw Error('columns');const sku=row[0].trim(),q=row[1],p=row[2];
   if(!sku||!/^\d+$/.test(q)||!/^\d+(?:\.\d{1,2})?$/.test(p))throw Error('value');
   const quantity=Number(q),parts=p.split('.'),cents=Number(parts[0])*100+Number((parts[1]||'').padEnd(2,'0'));
   const subtotal=quantity*cents,item=map.get(sku)||{sku,quantity:0,cents:0};item.quantity+=quantity;item.cents+=subtotal;map.set(sku,item);total+=subtotal;
  }
  function compare(a,b){const x=Array.from(a.sku,c=>c.codePointAt(0)),y=Array.from(b.sku,c=>c.codePointAt(0));for(let i=0;i<Math.min(x.length,y.length);i++)if(x[i]!==y[i])return x[i]-y[i];return x.length-y.length}
  function money(cents){return Math.floor(cents/100)+'.'+String(cents%100).padStart(2,'0')}
  output.textContent=JSON.stringify({items:Array.from(map.values()).sort(compare).map(x=>({sku:x.sku,quantity:x.quantity,subtotal:money(x.cents)})),total:money(total)});error.textContent='';
 }catch(e){output.textContent='';error.textContent='Invalid'}
};</script>'''


def test_category_registration_and_prediction_do_not_use_private_checks():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert {case["category"] for case in corpus["cases"]} == {"simple", "medium", "large", "underestimated"}
    assert len(corpus["cases"]) == 4
    values = []
    for case in corpus["cases"]:
        b = resolve_output_policy(corpus["policies"][1], case, corpus["prediction"])
        c = resolve_output_policy(corpus["policies"][2], case, corpus["prediction"])
        assert b["initial"] == c["initial"]
        values.append(b["initial"])
    assert values == [2048, 4096, 8192, 2048]
    assert corpus["registration"]["protocol"] == "prompt_json"


def test_category_report_does_not_hide_underestimation_failure():
    from tests.support.task_progress import progress_summary, summarize_categories
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    rows = []
    for case in corpus["cases"]:
        for policy in corpus["policies"]:
            success = not (case["category"] == "underestimated" and policy["id"] == "predicted_fixed")
            snapshots = [{"call": 0, "passed_checks": [], "failed_checks": ["goal"], "all_passed": False},
                         {"call": 2, "passed_checks": ["goal"] if success else [], "failed_checks": [] if success else ["goal"], "all_passed": success}]
            rows.append({"trial": 1, "id": case["id"], "category": case["category"], "condition": policy["id"],
                         "evaluation_complete": True, "calls": 2, "progress": progress_summary(snapshots, 2), "delivered": success,
                         "conservative_cost_usd": 0.01, "observation_errors": [], "receipts": []})
    result = summarize_categories(rows, corpus["policies"])
    assert result["simple"]["policies"]["predicted_fixed"]["functional_goals_met"] == 1
    assert result["underestimated"]["policies"]["predicted_fixed"]["functional_goals_met"] == 0
    assert result["underestimated"]["policies"]["predicted_adaptive"]["functional_goals_met"] == 1


@pytest.mark.browser
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser evaluator")
async def test_four_category_oracles_and_realistic_underestimate_reference():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    references = [REFERENCE_SCRATCHPAD, REFERENCE_SPLITTER, REFERENCE_INVENTORY, REFERENCE_CSV]
    for case, html in zip(corpus["cases"], references):
        result = await browser_checks(html, case["checks"])
        assert all(row["passed"] for row in result.values()), (case["id"], result)
    csv = corpus["cases"][-1]
    broken = REFERENCE_CSV.replace("function parseCSV(text){", "function parseCSV(text){text=text.replaceAll('\"','');")
    result = await browser_checks(broken, [check for check in csv["checks"] if check["id"] == "unclosed-quote"])
    assert not result["unclosed-quote"]["passed"]
    prose = await browser_checks('<p>All requirements completed.</p>', csv["checks"][:1])
    assert not prose["interface"]["passed"]


def test_json_results_compare_structure_and_types_not_substrings():
    from tests.support.task_progress import json_result_matches
    assert json_result_matches('{"total":"0.20","items":[]}', {"items": [], "total": "0.20"})
    assert not json_result_matches('{"total":0.20,"items":[]}', {"items": [], "total": "0.20"})
    assert not json_result_matches('I created the result', {"items": []})
    assert not json_result_matches('{"quantity":true}', {"quantity": 1})
