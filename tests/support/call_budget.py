"""Experimental per-call allowance; product defaults and model thinking are untouched."""
from copy import deepcopy
import json
from typing import Literal

from pydantic import ConfigDict, ValidationError, create_model

from gateway.action import ActionService
from gateway.action.model_action import InvalidModelAction, decode_action_object
from tests.support.evaluation import digest
from tests.support.runtime_efficiency import live_case
from tests.support.task_progress import decision_trace, progress_summary


def response_contract(flow, execution_path, *, final_answer=False):
    if not flow or final_answer:
        return None
    read = flow["read"]
    observed = any(row.get("kind") == "tool_call" and row.get("ok") is True
                   and row.get("tool_name") == read["tool_name"] and row.get("args") == read["args"]
                   for row in execution_path)
    if not observed:
        return {"max_action_chars": 1024, "allowed_calls": [read], "answer_fields": None}
    fields = flow.get("answer_fields")
    return {"max_action_chars": 1024, "allowed_calls": [], "answer_fields": fields} if fields else None


def call_allowance(contract):
    if contract is not None and type(contract.get("max_action_chars")) is int and 0 < contract["max_action_chars"] <= 1024:
        return {"initial": 4096, "ceiling": 8192, "source": "enforced_bounded_response"}
    return {"initial": 8192, "ceiling": 8192, "source": "unknown_output_conservative"}


def allowance_changes(receipts):
    changes = []
    for index, (previous, current) in enumerate(zip(receipts, receipts[1:]), 2):
        if previous["max_tokens"] == current["max_tokens"]:
            continue
        old_scope = (previous.get("output_budget") or {}).get("contract_hash")
        new_scope = (current.get("output_budget") or {}).get("contract_hash")
        reason = ("real_truncation_recovery" if previous.get("code") == "MODEL_OUTPUT_LIMIT" and old_scope == new_scope
                  else "runtime_output_scope_changed" if old_scope != new_scope
                  else "final_completion_boundary" if current.get("purpose") == "final_response" else "other_allowance_change")
        changes.append({"call": index, "before": previous["max_tokens"], "after": current["max_tokens"], "reason": reason})
    return changes


def validate_response_contract(action, contract):
    if contract is None:
        return
    if len(json.dumps(action.raw, ensure_ascii=False)) > contract["max_action_chars"]:
        raise InvalidModelAction("Response exceeds this Runtime phase's declared character bound")
    if action.kind == "tool_calls" and len(action.calls) == 1:
        call = action.calls[0]
        if {"tool_name": call.tool_name, "args": call.arguments} in contract["allowed_calls"]:
            return
    if action.kind == "answer" and contract["answer_fields"]:
        try:
            fields = {key: (Literal[tuple(values)], ...) for key, values in contract["answer_fields"].items()}
            model = create_model("FiniteRuntimeAnswer", __config__=ConfigDict(extra="forbid"), **fields)
            model.model_validate(decode_action_object(action.content))
            return
        except (ValueError, ValidationError) as exc:
            raise InvalidModelAction("Answer does not match the finite Runtime response contract") from exc
    raise InvalidModelAction("This Runtime phase only accepts the declared call or finite answer")


class CallBudgetService(ActionService):
    """Common phase contract for all arms; only the candidate changes per-call allowance."""
    def __init__(self, *, original, flow, aware):
        super().__init__(conversation_core=original.conversation_core, event_emitter=original.event_emitter,
                         task_service=original.task_service, capability_service=original.capability_service)
        self.flow, self.aware, self.current = deepcopy(flow), aware, {}

    def _output_limits(self, run):
        if not self.aware:
            return super()._output_limits(run)
        selected = call_allowance(self.current.get(run.run_id))
        return selected["initial"], selected["ceiling"]

    async def _call_model(self, run, messages, model_step_id, *, final_answer=False, **kwargs):
        contract = response_contract(self.flow, run.execution_path, final_answer=final_answer)
        self.current[run.run_id] = contract
        shape_hash = digest(contract)
        if self.aware and run.context.metadata.get("eval_output_scope") != shape_hash:
            run.model_recovery.pop("output_tokens", None)
        run.context.metadata["eval_output_scope"] = shape_hash
        if contract is not None:
            messages = [*messages, {"role": "system", "content": (
                "Current Runtime response contract (enforced for this call):\n"
                + json.dumps(contract, ensure_ascii=False, sort_keys=True)
                + "\nPropose exactly one declared call. When answer_fields is present, return an answer action whose content is a JSON object with exactly those keys and one listed value per key. No other action can execute in this phase."
            )}]
        config = run.context.user_config
        initial, ceiling = self._output_limits(run)
        run.context.user_config = {**(config or {}), "_eval_output_budget": {
            "initial": initial, "ceiling": ceiling, "contract_hash": shape_hash,
            "source": call_allowance(contract)["source"] if self.aware else "unchanged_comparator",
            "max_action_chars": (contract or {}).get("max_action_chars"), "final_answer_only": final_answer,
        }}
        try:
            return await super()._call_model(run, messages, model_step_id, final_answer=final_answer, **kwargs)
        finally:
            run.context.user_config = config

    def _validate_answer_evidence(self, run, action):
        super()._validate_answer_evidence(run, action)
        validate_response_contract(action, self.current.get(run.run_id))


async def call_budget_case(case, endpoint, root, condition, *, policy):
    def factory(original):
        return CallBudgetService(original=original, flow=case.get("runtime_output_flow"), aware=policy.get("call_aware", False))
    row = await live_case(case, endpoint, root, condition, policy=policy, action_service_factory=factory)
    required = case["expect"].get("required_tools", [])
    facts = [fact for step in row["decision_trace"] for fact in step["observations"]]
    for name in required:
        if not any(fact["tool"] == name and fact["ok"] is True for fact in facts):
            row["failures"].append("missing_successful_tool:" + name)
    if "answer_json" in case["expect"]:
        from tests.support.task_progress import json_result_matches
        if not json_result_matches(row["answer"], case["expect"]["answer_json"]):
            row["failures"].append("answer_json_mismatch")
    row["delivered"] = not row["failures"]
    if row["progress"] is None:
        total = len(row["decision_trace"])
        initial = {"call": 0, "passed_checks": [], "failed_checks": ["actual_read", "finite_answer"], "all_passed": False, "artifact_hash": None}
        read_call = next((step["call"] for step in row["decision_trace"] if any(fact["tool"] in required and fact["ok"] is True for fact in step["observations"])), None)
        snapshots = [initial]
        if read_call is not None:
            snapshots.append({**initial, "call": read_call, "passed_checks": ["actual_read"], "failed_checks": ["finite_answer"]})
        passed = ["actual_read", "finite_answer"] if row["delivered"] else (["actual_read"] if read_call is not None else [])
        snapshots.append({**initial, "call": total, "passed_checks": passed, "failed_checks": [key for key in initial["failed_checks"] if key not in passed], "all_passed": row["delivered"]})
        row["progress"] = {**progress_summary(snapshots, total), "snapshots": snapshots, "evaluation_errors": [],
                           "changed_artifact_versions": 0, "final_artifact_chars": 0, "duplicate_observation_results": 0}
        events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        calls = [event["payload"] for event in events if event["event_type"] == "model.call.recorded"]
        observations = [event["payload"] for event in events if event["event_type"] == "action.observation.committed"]
        receipts = endpoint.receipts[-total:] if total else []
        row["decision_trace"] = decision_trace(receipts, calls, observations, row["progress"])
        (root / "decision-trace.json").write_text(json.dumps(row["decision_trace"], ensure_ascii=False, indent=2), encoding="utf-8")
    count = len(row["decision_trace"])
    row["budget_adjustments"] = allowance_changes(endpoint.receipts[-count:] if count else [])
    return row
