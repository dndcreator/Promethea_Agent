"""Evaluation-only budgets, deterministic evidence checks and Judge validation."""
from dataclasses import dataclass, field
import hashlib
import json
import math
import time


class BudgetExceeded(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass
class Budget:
    max_calls: int = 30
    max_tokens: int = 16000
    seconds: float = 180
    calls: int = 0
    tokens: int = 0
    max_cost_usd: float | None = None
    cost_usd: float = 0
    usage_known: bool = True
    started: float = field(default_factory=time.monotonic)

    def admit(self, messages, output_tokens, rates=None):
        # A deliberately conservative text reserve; not a provider billing quote.
        reserve = len(json.dumps(messages, ensure_ascii=False).encode()) + output_tokens + 512
        if not self.usage_known or self.calls >= self.max_calls or self.tokens + reserve > self.max_tokens or self.remaining() <= 0:
            raise BudgetExceeded("call/token/deadline budget exhausted or provider usage unavailable")
        if self.max_cost_usd is not None:
            if rates is None or self.cost_usd + (reserve * rates[0] + output_tokens * rates[1]) / 1_000_000 > self.max_cost_usd:
                raise BudgetExceeded("currency budget unavailable or insufficient")
        self.calls += 1  # failures consume admission too; no hidden retries

    def remaining(self):
        return max(0.0, self.seconds - (time.monotonic() - self.started))

    def settle(self, usage, rates=None):
        if not usage or any(usage.get(key) is None for key in ("prompt_tokens", "completion_tokens")):
            self.usage_known = False
            return
        values = [usage[key] for key in ("prompt_tokens", "completion_tokens")]
        if any(not isinstance(value, int) or value < 0 for value in values):
            self.usage_known = False
            return
        self.tokens += sum(values)
        if rates is not None:
            self.cost_usd += (values[0] * rates[0] + values[1] * rates[1]) / 1_000_000


def hard_checks(case, evidence):
    expected, errors = case.get("expect", {}), []
    if evidence.get("status") not in {"success", "completed"}:
        errors.append("runtime_not_completed")
    called = set(evidence.get("tools", []))
    for name in expected.get("required_tools", []):
        if name not in called:
            errors.append("missing_tool:" + name)
    for name in expected.get("forbidden_tools", []):
        if name in called:
            errors.append("forbidden_tool:" + name)
    for path, content in expected.get("artifacts", {}).items():
        if evidence.get("artifacts", {}).get(path) != content:
            errors.append("artifact_mismatch:" + path)
    for text in expected.get("answer_contains", []):
        if text not in evidence.get("answer", ""):
            errors.append("answer_missing:" + text)
    if case["kind"] == "classification":
        candidates = evidence.get("candidates", [])
        if expected.get("no_candidates"):
            if candidates:
                errors.append("unsupported_memory_candidate")
        elif not candidates:
            # Rejecting a hypothetical/ephemeral fact altogether is also safe.
            if "gate_not" not in expected:
                errors.append("missing_memory_candidate")
        else:
            for candidate in candidates:
                for key in ("modality", "persistence"):
                    if key in expected and candidate.get(key) != expected[key]:
                        errors.append("memory_" + key)
                gate = candidate.get("gate")
                if "gate" in expected and gate != expected["gate"]:
                    errors.append("memory_gate")
                if "gate_not" in expected and gate == expected["gate_not"]:
                    errors.append("unsafe_memory_gate")
    if case["kind"] == "retrieval":
        rows = evidence.get("candidates", [])
        text = json.dumps(rows, ensure_ascii=False)
        if expected.get("empty") and rows:
            errors.append("irrelevant_recall_filler")
        if expected.get("relevant") and expected["relevant"] not in text:
            errors.append("recall_miss")
        if expected.get("forbidden") and expected["forbidden"] in text:
            errors.append("recall_owner_leak")
    if evidence.get("history_matches") is False:
        errors.append("history_mismatch")
    if "model_calls" in expected and evidence.get("model_calls") != expected["model_calls"]:
        errors.append("unexpected_autonomous_model_calls")
    if expected.get("requires_model") and not evidence.get("model_calls"):
        errors.append("autonomous_cycle_not_executed")
    return sorted(set(errors))


def validate_judgment(value, dimensions, evidence_ids):
    fields = {"task_outcome", "behavior", "incomplete_reason", "reason_evidence_ids", "dimensions", "evidence_ids", "reason"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Judge must return the exact structured envelope")
    if value["task_outcome"] not in {"completed", "incomplete", "unverifiable"} or value["behavior"] not in {"correct", "incorrect", "insufficient_evidence"}:
        raise ValueError("Invalid task outcome or behavior judgment")
    if value["incomplete_reason"] not in {"none", "capability_unavailable", "permission_denied", "execution_error", "missing_information", "unknown"}:
        raise ValueError("Invalid incomplete reason")
    if (value["task_outcome"] == "completed") != (value["incomplete_reason"] == "none"):
        raise ValueError("Incomplete reason contradicts task outcome")
    allowed = {"pass", "fail", "uncertain"}
    scores = value["dimensions"]
    if not isinstance(scores, dict) or set(scores) != set(dimensions) or any(score not in allowed for score in scores.values()):
        raise ValueError("Judge dimensions do not match the rubric")
    behavior_scores = [score for name, score in scores.items() if name != "task_fulfillment"]
    behavior = "incorrect" if "fail" in behavior_scores else "insufficient_evidence" if not behavior_scores or "uncertain" in behavior_scores else "correct"
    if value["behavior"] != behavior:
        raise ValueError("Judge behavior contradicts its dimensions")
    if "task_fulfillment" in scores and scores["task_fulfillment"] != {"completed": "pass", "incomplete": "fail", "unverifiable": "uncertain"}[value["task_outcome"]]:
        raise ValueError("Task fulfillment contradicts task outcome")
    refs = value["evidence_ids"]
    if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in evidence_ids for ref in refs):
        raise ValueError("Judge cited nonexistent evidence")
    if (value["behavior"] != "insufficient_evidence" or value["task_outcome"] != "unverifiable") and not refs:
        raise ValueError("A decisive judgment needs observable evidence")
    cause_refs = value["reason_evidence_ids"]
    if not isinstance(cause_refs, list) or any(not isinstance(ref, str) or ref not in evidence_ids for ref in cause_refs):
        raise ValueError("Incomplete reason cited nonexistent evidence")
    if value["incomplete_reason"] not in {"none", "unknown"} and not cause_refs:
        raise ValueError("A known blocker requires Runtime evidence, not an agent claim")
    if value["incomplete_reason"] not in {"none", "unknown"} and not (
        isinstance(evidence_ids, dict) and any(ref.startswith(("runtime:", "event:")) and isinstance(evidence_ids[ref], dict) for ref in cause_refs)
    ):
        raise ValueError("A known blocker requires a Runtime-owned evidence record")
    if not isinstance(value["reason"], str) or not value["reason"].strip() or len(value["reason"]) > 2000:
        raise ValueError("Judge reason is missing or too large")
    return value


def judge_matches_expectation(case, judgment):
    expected = case.get("judge_expect", {"task_outcome": ["completed"], "behavior": ["correct"]})
    return all(judgment.get(axis) in values for axis, values in expected.items())


def calibration_ready(cases, minimum=3):
    reviewed = [case for case in cases if case.get("reviewed_by") and case.get("reviewed_at")]
    return len(reviewed) >= minimum and {case["expected"].get("behavior") for case in reviewed} == {"correct", "incorrect", "insufficient_evidence"}


def summarize(rows):
    groups = {}
    for group in sorted({row["group"] for row in rows}):
        items = [row for row in rows if row["group"] == group]
        passed = sum(row.get("hard_pass") is True for row in items)
        n, z = len(items), 1.96
        rate = passed / n
        center = (rate + z * z / (2 * n)) / (1 + z * z / n)
        width = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        groups[group] = {"trials": n, "hard_passes": passed, "hard_pass_rate": rate,
                         "wilson95": [max(0, center - width), min(1, center + width)],
                         "judge_measured": sum(bool(row.get("judge")) for row in items),
                         "evaluation_errors": sum(bool(row.get("evaluation_error")) for row in items),
                         "task_outcomes": {outcome: sum(row.get("judge", {}).get("task_outcome") == outcome for row in items) for outcome in ("completed", "incomplete", "unverifiable")},
                         "behavior_judgments": {outcome: sum(row.get("judge", {}).get("behavior") == outcome for row in items) for outcome in ("correct", "incorrect", "insufficient_evidence")}}
    return groups


def compare_behavior(before, after):
    keys = ("mode", "corpus_hash", "rubric_hash", "case_ids", "repeat")
    if any(before.get(key) != after.get(key) for key in keys):
        raise ValueError("Incompatible corpus/rubric/case selection/repetition; cannot claim improvement")
    if any(report.get("completed_trials") != report.get("planned_trials") or report.get("stop_reason") for report in (before, after)):
        raise ValueError("Incomplete or budget-stopped runs cannot establish comparable quality")
    return {group: {"before": before["groups"].get(group), "after": after["groups"].get(group)}
            for group in before["groups"].keys() | after["groups"].keys()}
