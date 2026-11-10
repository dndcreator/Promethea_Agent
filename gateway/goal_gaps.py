"""Bounded goal-relative execution state, inspired by Beyond Memory / PoS.

https://arxiv.org/abs/2610.01415
No belief graph, model-based sentinel, or additional inference loop.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class GapContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GapCheck(GapContract):
    tool_name: str = Field(min_length=1, max_length=160)
    pointer: str = Field(max_length=300, pattern=r"^(?:/(?:[^~]|~[01])*)*$")
    expected: Any

    @model_validator(mode="after")
    def bound_expected(self):
        if len(json.dumps(self.expected, ensure_ascii=False, allow_nan=False)) > 128:
            raise ValueError("gap checks require a small expected value")
        return self


class GapSpec(GapContract):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,47}$")
    kind: Literal["epistemic", "achievement"]
    requirement: str = Field(min_length=1, max_length=400)
    check: GapCheck | None = None


class GapChange(GapContract):
    id: str
    state: Literal["open", "blocked", "resolved"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)


class GapRecoveryDecision(GapContract):
    strategy: Literal["investigate", "replan", "retry"]
    reason: str = Field(min_length=1, max_length=400)
    evidence_refs: list[str] = Field(min_length=1, max_length=4)
    repair_refs: list[str] = Field(default_factory=list, max_length=4)


class GapDelta(GapContract):
    revision: StrictInt = Field(ge=0)
    create: list[GapSpec] = Field(default_factory=list, max_length=8)
    updates: list[GapChange] = Field(default_factory=list, max_length=8)
    focus: list[str] | None = Field(default=None, max_length=4)
    recovery: GapRecoveryDecision | None = None


class GoalGap(GapSpec):
    declared_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    state: Literal["open", "blocked", "resolved"] = "open"
    support: Literal["none", "inferred", "checked"] = "none"
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)


class GapFrame(GapContract):
    signature: str
    progress: bool = False
    outcome: str = ""
    failures: list[str] = Field(default_factory=list, max_length=16)


class GapFailedCall(GapContract):
    signature: str
    observation_id: str
    retryable: bool = False
    count: int = 1
    retries: int = 0


class GapRecoveryState(GapContract):
    mode: Literal["execute", "reassess", "trial"] = "execute"
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list, max_length=4)
    failed_calls: list[GapFailedCall] = Field(default_factory=list, max_length=32)
    decision: GapRecoveryDecision | None = None
    proposal: str = ""
    rejections: int = 0
    failed_trials: int = 0


class GapBarrier(GapContract):
    loop_id: str
    offset: int = Field(ge=0)


class GoalGapState(GapContract):
    version: Literal["goal.gaps.v1"] = "goal.gaps.v1"
    revision: int = Field(default=0, ge=0)
    gaps: list[GoalGap] = Field(default_factory=list, max_length=32)
    focus: list[str] = Field(default_factory=list, max_length=4)
    recent: list[GapFrame] = Field(default_factory=list, max_length=16)
    barriers: dict[str, GapBarrier] = Field(default_factory=dict, max_length=32)
    recovery: GapRecoveryState = Field(default_factory=GapRecoveryState)

    @model_validator(mode="after")
    def valid_identity(self):
        ids = [gap.id for gap in self.gaps]
        if len(set(ids)) != len(ids) or len(set(self.focus)) != len(self.focus) or not set(self.focus).issubset(ids):
            raise ValueError("invalid gap identities or focus")
        if any(gap.state == "resolved" and gap.support == "none" for gap in self.gaps):
            raise ValueError("resolved gap requires a support classification")
        return self


class GoalGapView(BaseModel):
    """Public projection omits internal repetition-monitor frames."""
    model_config = ConfigDict(extra="ignore")
    version: Literal["goal.gaps.v1"] = "goal.gaps.v1"
    revision: int = 0
    gaps: list[GoalGap] = Field(default_factory=list)
    focus: list[str] = Field(default_factory=list)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def _pointer(value: Any, pointer: str) -> Any:
    for part in pointer.split("/")[1:] if pointer else []:
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not key.isdigit() or str(int(key)) != key:
                raise ValueError("invalid array pointer")
            value = value[int(key)]
        elif isinstance(value, dict):
            value = value[key]
        else:
            raise ValueError("pointer does not address a value")
    return value


def apply_gap_delta(state: GoalGapState, raw: dict, observations: list[dict], *, max_gaps: int = 12, max_updates: int = 6, loop_id: str = "") -> GoalGapState:
    if len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode()) > 8000:
        raise ValueError("gap delta exceeds 8 KB")
    delta = GapDelta.model_validate(raw)
    if delta.revision != state.revision:
        raise ValueError(f"stale gap revision: current {state.revision}")
    if len(delta.create) + len(delta.updates) > max_updates:
        raise ValueError("too many gap changes in one decision")
    result = state.model_copy(deep=True)
    gaps = {gap.id: gap for gap in result.gaps}
    for item in delta.create:
        if item.id in gaps:
            raise ValueError("gap identity, requirement and check are immutable; reopen existing gaps")
        gaps[item.id] = GoalGap(**item.model_dump())
        result.barriers[item.id] = GapBarrier(loop_id=loop_id, offset=len(observations))
    if delta.create and len(gaps) > max_gaps:
        raise ValueError("gap capacity reached; do not rename or discard outstanding requirements")
    evidence = {item["observation_id"]: item for item in observations if item.get("observation_id")}
    positions = {item.get("observation_id"): index for index, item in enumerate(observations)}
    seen = set()
    for update in delta.updates:
        if update.id not in gaps or update.id in seen:
            raise ValueError("unknown or duplicate gap update")
        seen.add(update.id)
        gap = gaps[update.id]
        if any(ref not in evidence for ref in update.evidence_refs):
            raise ValueError("gap evidence must reference supplied Runtime observations")
        refs = [evidence[ref] for ref in update.evidence_refs]
        if update.state == "resolved" and (not refs or not all(item.get("ok") is True for item in refs)):
            raise ValueError("resolution requires successful Runtime evidence; refusal is not completion")
        support = "none"
        if update.state == "resolved":
            support = "inferred"
            if gap.check is not None:
                matches = []
                for item in refs:
                    if item.get("tool_name") != gap.check.tool_name:
                        continue
                    try:
                        barrier = result.barriers.get(gap.id)
                        if barrier is None or barrier.loop_id == loop_id and positions[item["observation_id"]] < barrier.offset:
                            raise ValueError("check must be declared before the verifying observation")
                        actual = _pointer(item.get("structured_result"), gap.check.pointer)
                        # Canonical JSON equality avoids Python's True == 1 coercion.
                        matches.append(fingerprint(actual) == fingerprint(gap.check.expected))
                    except (KeyError, IndexError, TypeError, ValueError):
                        matches.append(False)
                if not matches or not all(matches):
                    raise ValueError("declared gap check did not pass")
                support = "checked"
        if gap.state == "resolved" and update.state != "resolved":
            gap.declared_at = datetime.now(timezone.utc).isoformat()
            result.barriers[gap.id] = GapBarrier(loop_id=loop_id, offset=len(observations))
        gap.state = update.state
        gap.support = support
        gap.evidence_refs = list(dict.fromkeys(update.evidence_refs))
    if delta.focus is not None:
        if len(set(delta.focus)) != len(delta.focus) or any(item not in gaps or gaps[item].state == "resolved" for item in delta.focus):
            raise ValueError("focus must reference distinct unresolved gaps")
        result.focus = list(delta.focus)
    else:
        result.focus = [item for item in result.focus if gaps[item].state != "resolved"]
    result.gaps = list(gaps.values())
    previous = {gap.id: gap for gap in state.gaps}
    progress = any(gap.id in previous and gap.state == "resolved" and gap.support == "checked" and previous[gap.id].state != "resolved" for gap in result.gaps)
    if progress and result.recent:
        result.recent[-1].progress = True
    if progress:
        result.recovery = GapRecoveryState()
    blocked_refs = [ref for update in delta.updates if update.state == "blocked"
                    and (not result.focus or update.id in result.focus) for ref in update.evidence_refs]
    if blocked_refs and not progress:
        _reassess(result, "declared_blocker", blocked_refs)
    if delta.recovery is not None and not progress:
        refs = delta.recovery.evidence_refs + delta.recovery.repair_refs
        if any(ref not in evidence for ref in refs):
            raise ValueError("recovery requires supplied Runtime observation references")
        if result.recovery.mode == "execute" and set(delta.recovery.evidence_refs).intersection(row.observation_id for row in result.recovery.failed_calls):
            _reassess(result, "failed_path_requires_reassessment", delta.recovery.evidence_refs)
        if result.recovery.mode != "reassess":
            raise ValueError("no Runtime reassessment is pending")
        result.recovery.decision = delta.recovery
    if result.model_dump() != state.model_dump():
        result.revision += 1
    return result


def gap_outcome(state: GoalGapState) -> dict:
    counts = {name: sum(gap.state == name for gap in state.gaps) for name in ("open", "blocked", "resolved")}
    return {"tracked": len(state.gaps), **counts,
            "checks_passed": sum(gap.state == "resolved" and gap.support == "checked" for gap in state.gaps),
            # All model-declared checks passing is NOT proof of full user-goal coverage.
            "goal_verification": "unknown"}


def gap_event_delta(previous: GoalGapState, state: GoalGapState) -> dict:
    before = {gap.id: gap.model_dump() for gap in previous.gaps}
    return {"gap_revision": state.revision, "focus": state.focus, "summary": gap_outcome(state),
            "changes": [gap.model_dump() for gap in state.gaps if before.get(gap.id) != gap.model_dump()]}


def call_signature(tool_name: str, args: dict) -> str:
    return fingerprint({"tool": tool_name, "args": args})


def _reassess(state: GoalGapState, reason: str, refs: list[str]) -> None:
    state.recovery.mode = "reassess"
    state.recovery.reason = reason
    state.recovery.evidence_refs = list(dict.fromkeys(refs))[-4:]
    state.recovery.decision = None
    state.recovery.proposal = ""


def observe_gap_step(state: GoalGapState, path: list[dict], observations: list[dict], *, window: int = 4) -> GoalGapState:
    # A slice ending is not a new obstacle in the environment.
    settled = [item for item in observations if (item.get("error") or {}).get("category") not in
               {"approval", "validation", "model_output", "budget", "progress_control", "execution_boundary", "completion"}]
    if not settled:
        return state
    ids = {item["tool_call_id"] for item in settled}
    calls = [{"tool": item.get("tool_name"), "args": item.get("args")} for item in path if item.get("tool_call_id") in ids]
    facts = [{"tool": item.get("tool_name"), "ok": item.get("ok"),
              "result": item.get("structured_result") if item.get("structured_result") is not None else item.get("model_projection"),
              "error": {key: item["error"].get(key) for key in ("code", "category", "retryable")} if item.get("error") else None} for item in settled]
    result = state.model_copy(deep=True)
    try:
        signature = fingerprint({"calls": calls, "facts": facts})
        outcome = fingerprint(facts)
    except (TypeError, ValueError):
        # Monitoring must not turn an unusual tool payload into a failed action.
        return state
    if any(item.get("tool_name") == "runtime.user_input" for item in settled):
        result.recovery.rejections = result.recovery.failed_trials = 0
        if result.recovery.mode != "execute":
            _reassess(result, "user_report_requires_verification", result.recovery.evidence_refs + [item["observation_id"] for item in settled])
    failures = [fingerprint({"tool": item.get("tool_name"), "code": (item.get("error") or {}).get("code"),
                             "category": (item.get("error") or {}).get("category")}) for item in settled if not item.get("ok")]
    by_id = {item.get("tool_call_id"): item for item in path if item.get("executed", True)}
    for item in settled:
        call = by_id.get(item.get("tool_call_id"))
        if item.get("ok") or call is None:
            continue
        key = call_signature(call.get("tool_name"), call.get("args") or {})
        prior = next((row for row in result.recovery.failed_calls if row.signature == key), None)
        if prior:
            prior.count += 1
            prior.observation_id = item["observation_id"]
            prior.retryable = bool((item.get("error") or {}).get("retryable"))
        elif len(result.recovery.failed_calls) < 32:
            result.recovery.failed_calls.append(GapFailedCall(signature=key, observation_id=item["observation_id"],
                retryable=bool((item.get("error") or {}).get("retryable"))))
    trial = result.recovery.mode == "trial"
    new_evidence = not failures and outcome not in {frame.outcome for frame in result.recent if frame.outcome}
    if trial and new_evidence:
        result.recovery.mode = "execute"
        result.recovery.reason = ""
        result.recovery.evidence_refs = []
        result.recovery.decision = None
        result.recovery.proposal = ""
        result.recovery.rejections = result.recovery.failed_trials = 0
        result.recent = []
    # New evidence can end a recovery trial, but does not certify goal completion.
    result.recent = [*result.recent, GapFrame(signature=signature, outcome=outcome, failures=failures[:16])][-window:]
    recent = result.recent
    stalled = len(recent) == window and not any(frame.progress for frame in recent) and len({frame.signature for frame in recent}) < len(recent)
    repeated_failure = bool(failures and any(key in frame.failures for frame in recent[:-1] for key in failures))
    if trial and not new_evidence:
        result.recovery.failed_trials += 1
        _reassess(result, "recovery_produced_no_new_evidence", [item["observation_id"] for item in settled if not failures or not item.get("ok")])
    elif stalled or repeated_failure or any(not item.get("ok") and (item.get("error") or {}).get("retryable") is False for item in settled):
        _reassess(result, "repeated_failure" if repeated_failure else "failed_precondition" if failures else "repeated_result", [item["observation_id"] for item in settled if not failures or not item.get("ok")])
    result.revision += 1
    return result


def admit_gap_action(state: GoalGapState, calls: list[dict], observations: list[dict], *, diagnostic: bool = False) -> tuple[GoalGapState, str]:
    """Admit one concrete recovery proposal, never grant tool authorization."""
    result = state.model_copy(deep=True)
    control = result.recovery
    proposal = fingerprint(calls)
    if control.mode == "trial" and control.proposal == proposal:
        return state, ""  # The same owned proposal may be waiting for approval.
    failed = {row.signature: row for row in control.failed_calls}
    repeated = [failed[key] for call in calls if (key := call_signature(call["tool_name"], call["args"])) in failed
                and (not failed[key].retryable or failed[key].count >= 2)]
    if repeated and control.mode != "reassess":
        _reassess(result, "failed_path_requires_reassessment", [row.observation_id for row in repeated])
    error = ""
    if control.mode == "reassess":
        decision = control.decision
        known = {row.get("observation_id"): index for index, row in enumerate(observations)}
        if decision is None and diagnostic and not repeated:
            pass
        elif decision is None:
            error = "Attach gap_update.recovery with a strategy, reason and current obstacle evidence before tool execution."
        elif not set(decision.evidence_refs).intersection(control.evidence_refs):
            error = "The recovery decision must address a current Runtime obstacle."
        elif repeated:
            repairs = [ref for ref in decision.repair_refs if ref in known and observations[known[ref]].get("ok") is True
                       and observations[known[ref]].get("tool_name") != "runtime.user_input"]
            if len({row.signature for row in repeated}) != len(repeated) or decision.strategy != "retry" or any(row.retries >= 1 or not any(known[ref] > known.get(row.observation_id, len(observations)) for ref in repairs) for row in repeated):
                error = "This failed call cannot be replayed without a bounded retry decision and newer successful repair evidence. Choose another method, inspect capabilities, or await the user."
        if not error:
            control.mode = "trial"
            control.proposal = proposal
            for row in repeated:
                row.retries += 1
    if error:
        control.rejections += 1
        control.decision = None
    if result.model_dump() != state.model_dump():
        result.revision += 1
    return result, error


def gap_projection(state: GoalGapState, *, context_chars: int = 2400, window: int = 4, feedback: str = "", observations: list[dict] | None = None) -> dict:
    unresolved = [gap for gap in state.gaps if gap.state != "resolved"]
    visible = [*unresolved, *[gap for gap in state.gaps if gap.state == "resolved"]]
    recent = state.recent[-window:]
    stalled = len(recent) == window and not any(frame.progress for frame in recent) and len({frame.signature for frame in recent}) < len(recent)
    projection = {"revision": state.revision, "focus": state.focus, "summary": gap_outcome(state),
                  "gaps": [{"id": gap.id, "kind": gap.kind, "state": gap.state, "support": gap.support,
                            "requirement": gap.requirement[:96 if gap.state != "resolved" else 32]} for gap in visible]}
    candidates = sorted(unresolved, key=lambda gap: gap.id not in state.focus)
    checks = {gap.id: gap.check.model_dump() for gap in candidates if gap.check is not None}
    if checks:
        projection["focus_checks"] = checks
    if stalled or state.recovery.mode == "reassess":
        projection["recovery"] = "Repeated execution without accepted progress. Reconsider the unresolved gap: change evidence or method, clarify, or report blocked. Keep all safety/approval constraints."
        projection["execution_control"] = {"mode": "reassess", "reason": state.recovery.reason,
            "evidence_refs": state.recovery.evidence_refs,
            "required": "tool proposals need gap_update.recovery; capability inspection, answer and await_user remain available"}
    if feedback:
        projection["update_rejected"] = feedback[:200]
    obstacles = [
        {"observation_id": item["observation_id"], "subject": item.get("tool_name"),
         "code": (item.get("error") or {}).get("code"),
         "message": str((item.get("error") or {}).get("message") or "")[:160]}
        for item in (observations or [])[-window:]
        if not item.get("ok") and item.get("observation_id")
    ]
    if obstacles:
        projection["recent_obstacles"] = obstacles
    while len(json.dumps(projection, ensure_ascii=False)) > context_chars and obstacles:
        obstacles.pop(0)
    if not obstacles:
        projection.pop("recent_obstacles", None)
    # Keep every outstanding id/state visible; shorten text rather than dropping goals.
    while len(json.dumps(projection, ensure_ascii=False)) > context_chars and any(item["requirement"] for item in projection["gaps"]):
        for item in projection["gaps"]:
            item["requirement"] = item["requirement"][:-16]
    if len(json.dumps(projection, ensure_ascii=False)) > context_chars:
        projection["gaps"] = [{"id": gap.id, "state": gap.state} for gap in visible]
    while len(json.dumps(projection, ensure_ascii=False)) > context_chars and checks:
        checks.pop(next(reversed(checks)))
    if not checks:
        projection.pop("focus_checks", None)
    return projection
