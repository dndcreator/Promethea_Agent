"""Bounded goal-relative execution state, inspired by Beyond Memory / PoS.

https://arxiv.org/abs/2610.01415
No belief graph, model-based sentinel, or additional inference loop.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


_NON_GOAL_CATEGORIES = frozenset({"approval", "validation", "model_output", "budget", "progress_control",
                                  "execution_boundary", "completion"})


class GapContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GapBinding(GapContract):
    gap_id: str
    pointer: str = Field(max_length=300, pattern=r"^(?:/(?:[^~]|~[01])*)*$")
    source_pointer: str = Field(max_length=300, pattern=r"^(?:/(?:[^~]|~[01])*)*$")


class GapCheck(GapContract):
    tool_name: str = Field(min_length=1, max_length=160)
    pointer: str = Field(max_length=300, pattern=r"^(?:/(?:[^~]|~[01])*)*$")
    expected: Any
    bindings: list[GapBinding] = Field(default_factory=list, max_length=4)

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
    depends_on: list[str] = Field(default_factory=list, max_length=8)


def _dependency_order(gaps):
    ordered, visiting, done = [], set(), set()

    def visit(gap_id):
        if gap_id in visiting or gap_id not in gaps:
            raise ValueError("gap dependencies must reference known gaps and cannot form cycles")
        if gap_id in done:
            return
        visiting.add(gap_id)
        gap = gaps[gap_id]
        if len(set(gap.depends_on)) != len(gap.depends_on):
            raise ValueError("duplicate gap dependency")
        if gap.check and any(binding.gap_id not in gap.depends_on for binding in gap.check.bindings):
            raise ValueError("check bindings must reference declared dependencies")
        for parent in gap.depends_on:
            visit(parent)
            if gap.check and gaps[parent].check is None:
                raise ValueError("a prerequisite gap requires a verification check")
        visiting.remove(gap_id)
        done.add(gap_id)
        ordered.append(gap_id)

    for gap_id in gaps:
        visit(gap_id)
    return ordered


def reasoning_delivery_gaps(tree_id: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: dict[str, GapSpec] = {}
    for step in steps:
        try:
            spec = GapSpec.model_validate(step)
        except (ValueError, TypeError):
            continue
        if spec.check and spec.check.tool_name != "reasoning.run":
            if spec.id in specs and specs[spec.id] != spec:
                return []
            specs[spec.id] = spec
    # A selected step cannot depend on a discarded planning branch.
    while missing := {key for key, spec in specs.items() if set(spec.depends_on) - specs.keys()}:
        for key in missing:
            del specs[key]
    try:
        ordered = _dependency_order(specs)
    except ValueError:
        return []
    ids = {key: "reason_" + fingerprint([tree_id, key])[:24] for key in ordered}
    result = []
    for key in ordered:
        row = specs[key].model_dump()
        row["id"] = ids[key]
        row["depends_on"] = [ids[parent] for parent in row["depends_on"]]
        for binding in row["check"]["bindings"]:
            binding["gap_id"] = ids[binding["gap_id"]]
        result.append(row)
    return result


class GapChange(GapContract):
    id: str
    state: Literal["open", "blocked", "resolved"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    check: GapCheck | None = None


class GapRecoveryDecision(GapContract):
    strategy: Literal["investigate", "replan", "retry"]
    reason: str = Field(min_length=1, max_length=400)
    evidence_refs: list[str] = Field(min_length=1, max_length=4)
    repair_refs: list[str] = Field(default_factory=list, max_length=4)

class UserDependency(GapContract):
    kind: Literal["user_information", "user_choice", "human_action"]
    reason: str = Field(min_length=1, max_length=400)
    gap_ids: list[str] = Field(default_factory=list, max_length=8)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)


class TaskBelief(GapContract):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,47}$")
    gap_id: str
    claim: str = Field(min_length=1, max_length=320)
    evidence_refs: list[str] = Field(min_length=1, max_length=4)


class GapDelta(GapContract):
    revision: StrictInt = Field(ge=0)
    create: list[GapSpec] = Field(default_factory=list, max_length=8)
    updates: list[GapChange] = Field(default_factory=list, max_length=8)
    focus: list[str] | None = Field(default=None, max_length=4)
    recovery: GapRecoveryDecision | None = None
    belief_updates: list[TaskBelief] = Field(default_factory=list, max_length=4)


class GoalGap(GapSpec):
    declared_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    state: Literal["open", "blocked", "resolved"] = "open"
    support: Literal["none", "inferred", "reported", "checked"] = "none"
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def normalize_legacy_inferred_delivery(self):
        if self.kind == "achievement" and self.state == "resolved" and self.support == "inferred":
            self.state = "open"
        return self


class GapFrame(GapContract):
    signature: str
    progress: bool = False
    candidate_progress: bool = False
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
    beliefs: list[TaskBelief] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def valid_identity(self):
        ids = [gap.id for gap in self.gaps]
        if len(set(ids)) != len(ids) or len(set(self.focus)) != len(self.focus) or not set(self.focus).issubset(ids):
            raise ValueError("invalid gap identities or focus")
        if any(gap.state == "resolved" and gap.support == "none" for gap in self.gaps):
            raise ValueError("resolved gap requires a support classification")
        _dependency_order({gap.id: gap for gap in self.gaps})
        if len({belief.id for belief in self.beliefs}) != len(self.beliefs) or any(belief.gap_id not in ids for belief in self.beliefs):
            raise ValueError("invalid task belief identities or gap references")
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


def validate_gap_check_schema(check: GapCheck, schema: dict) -> None:
    node = schema
    for part in check.pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        if node.get("type") == "array" and key.isdecimal():
            node = node.get("items", {})
        else:
            node = node.get("properties", {}).get(key, {})
        if not isinstance(node, dict) or not node:
            return  # Undeclared provider payloads are still checked against actual observations.
    if node.get("x-promethea-evidence") == "transport":
        raise ValueError("Transport metadata does not verify a goal; check the returned object or effect.")
    actual = {str: "string", bool: "boolean", int: "integer", float: "number", dict: "object",
              list: "array", type(None): "null"}.get(type(check.expected))
    expected = node.get("type")
    types = expected if isinstance(expected, list) else [expected]
    if expected and actual not in types and not (actual == "integer" and "number" in types):
        raise ValueError(f"Gap check value type does not match the tool output schema at {check.pointer}.")


def apply_gap_delta(state: GoalGapState, raw: dict, observations: list[dict], *, max_gaps: int = 12, max_updates: int = 6, loop_id: str = "", output_schema: Callable[[str], dict] | None = None, allow_inferred_delivery: bool = False) -> GoalGapState:
    if len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode()) > 8000:
        raise ValueError("gap delta exceeds 8 KB")
    delta = GapDelta.model_validate(raw)
    if delta.revision != state.revision:
        raise ValueError(f"stale gap revision: current {state.revision}")
    if len(delta.create) + len(delta.updates) + len(delta.belief_updates) > max_updates:
        raise ValueError("too many gap changes in one decision")
    result = state.model_copy(deep=True)
    gaps = {gap.id: gap for gap in result.gaps}
    for item in delta.create:
        if item.id in gaps:
            raise ValueError("gap identity and requirement are immutable; update the existing gap")
        if item.check and output_schema:
            validate_gap_check_schema(item.check, output_schema(item.check.tool_name))
        gaps[item.id] = GoalGap(**item.model_dump())
        result.barriers[item.id] = GapBarrier(loop_id=loop_id, offset=len(observations))
    if delta.create and len(gaps) > max_gaps:
        raise ValueError("gap capacity reached; do not rename or discard outstanding requirements")
    evidence = {item["observation_id"]: item for item in observations if item.get("observation_id")}
    positions = {item.get("observation_id"): index for index, item in enumerate(observations)}
    updates = {update.id: update for update in delta.updates}
    if len(updates) != len(delta.updates) or not updates.keys() <= gaps.keys():
        raise ValueError("unknown or duplicate gap update")
    for update in delta.updates:
        if update.check is None:
            continue
        gap = gaps[update.id]
        if (update.state != "open" or update.evidence_refs or gap.support == "checked"
                or gap.check == update.check):
            raise ValueError("Revise a check only by reopening an unverified gap without submitting evidence.")
        if output_schema:
            validate_gap_check_schema(update.check, output_schema(update.check.tool_name))
        gap.check = update.check
        gap.declared_at = datetime.now(timezone.utc).isoformat()
        result.barriers[gap.id] = GapBarrier(loop_id=loop_id, offset=len(observations))
    changed_proofs = set()
    reported_delivery = False
    for gap_id in _dependency_order(gaps):
        gap = gaps[gap_id]
        update = updates.get(gap_id)
        invalidated = bool(changed_proofs.intersection(gap.depends_on))
        if update is None:
            if invalidated and gap.state == "resolved":
                gap.state, gap.support, gap.evidence_refs = "open", "none", []
                result.barriers[gap.id] = GapBarrier(loop_id=loop_id, offset=len(observations))
                changed_proofs.add(gap.id)
            continue
        previous_proof = (gap.state, gap.evidence_refs)
        if any(ref not in evidence for ref in update.evidence_refs):
            raise ValueError("gap evidence must reference supplied Runtime observations")
        refs = [evidence[ref] for ref in update.evidence_refs]
        if update.state == "resolved" and (not refs or not all(item.get("ok") is True for item in refs)):
            raise ValueError("resolution requires successful Runtime evidence; refusal is not completion")
        support = "none"
        if update.state == "resolved":
            prerequisites = [gaps[parent] for parent in gap.depends_on]
            if any(parent.state != "resolved" for parent in prerequisites):
                raise ValueError(f"gap {gap.id} needs resolved prerequisites: {', '.join(gap.depends_on)}")
            support = "inferred"
            if gap.check is not None:
                if any(parent.support != "checked" for parent in prerequisites):
                    raise ValueError(f"gap {gap.id} needs verified prerequisites: {', '.join(gap.depends_on)}")
                parent_refs = [ref for parent in prerequisites for ref in parent.evidence_refs]
                if any(ref not in positions for ref in parent_refs):
                    raise ValueError(f"gap {gap.id} needs the prerequisite evidence in this execution")
                if output_schema:
                    validate_gap_check_schema(gap.check, output_schema(gap.check.tool_name))
                matches = []
                for item in refs:
                    if item.get("tool_name") != gap.check.tool_name:
                        continue
                    try:
                        barrier = result.barriers.get(gap.id)
                        if barrier is None or barrier.loop_id == loop_id and positions[item["observation_id"]] < barrier.offset:
                            raise ValueError("check must be declared before the verifying observation")
                        actual = _pointer(item.get("structured_result"), gap.check.pointer)
                        if any(positions[ref] >= positions[item["observation_id"]] for ref in parent_refs):
                            raise ValueError("dependent evidence must follow prerequisite evidence")
                        for binding in gap.check.bindings:
                            parent = gaps[binding.gap_id]
                            actual_binding = _pointer(item.get("structured_result"), binding.pointer)
                            values = [_pointer(evidence[ref].get("structured_result"), binding.source_pointer)
                                      for ref in parent.evidence_refs
                                      if evidence[ref].get("tool_name") == parent.check.tool_name]
                            if not values or any(fingerprint(value) != fingerprint(actual_binding) for value in values):
                                raise ValueError("dependent evidence does not match the verified input")
                        # Canonical JSON equality avoids Python's True == 1 coercion.
                        matches.append(fingerprint(actual) == fingerprint(gap.check.expected))
                    except (KeyError, IndexError, TypeError, ValueError):
                        matches.append(False)
                if not matches or not all(matches):
                    raise ValueError(f"gap {gap.id}: declared check did not pass (including prerequisite evidence and bindings)")
                support = "checked"
        if gap.state == "resolved" and update.state != "resolved":
            gap.declared_at = datetime.now(timezone.utc).isoformat()
            result.barriers[gap.id] = GapBarrier(loop_id=loop_id, offset=len(observations))
        gap.state = update.state
        if gap.kind == "achievement" and support == "inferred":
            if allow_inferred_delivery:
                support = "reported"
                reported_delivery = True
            else:
                gap.state = "open"
        gap.support = support
        gap.evidence_refs = list(dict.fromkeys(update.evidence_refs))
        if previous_proof != (gap.state, gap.evidence_refs) and (previous_proof[0] == "resolved" or gap.state == "resolved"):
            changed_proofs.add(gap.id)
    if reported_delivery and any(gap.state != "resolved" for gap in gaps.values()):
        raise ValueError("A reported delivery cannot complete while other tracked gaps remain unresolved.")
    if delta.focus is not None:
        if len(set(delta.focus)) != len(delta.focus) or any(item not in gaps or gaps[item].state == "resolved" for item in delta.focus):
            raise ValueError("focus must reference distinct unresolved gaps")
        result.focus = list(delta.focus)
    else:
        result.focus = [item for item in result.focus if gaps[item].state != "resolved"]
    result.gaps = list(gaps.values())
    beliefs = {belief.id: belief for belief in result.beliefs}
    seen_ids = set()
    candidate_progress = False
    for belief in delta.belief_updates:
        if belief.id in seen_ids or belief.gap_id not in gaps or not belief.claim.strip():
            raise ValueError("task belief requires a unique identity, a known gap and a nonempty claim")
        seen_ids.add(belief.id)
        if any(evidence.get(ref, {}).get("ok") is not True or
               (evidence[ref].get("error") or {}).get("category") in _NON_GOAL_CATEGORIES
               for ref in belief.evidence_refs):
            raise ValueError("task belief requires successful Runtime observations")
        prior = beliefs.get(belief.id)
        if prior and prior.gap_id != belief.gap_id:
            raise ValueError("task belief identity cannot change its gap")
        claim = " ".join(belief.claim.split())
        if any(item.gap_id == belief.gap_id and " ".join(item.claim.split()) == claim for item in beliefs.values()):
            continue
        beliefs.pop(belief.id, None)
        beliefs[belief.id] = belief
        candidate_progress |= gaps[belief.gap_id].state != "resolved" and (not result.focus or belief.gap_id in result.focus)
    result.beliefs = list(beliefs.values())[-12:]
    if candidate_progress and result.recent:
        result.recent[-1].candidate_progress = True
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


def validate_partial_evidence(state: GoalGapState, refs: list[str], observations: list[dict]) -> None:
    if not state.gaps:
        return
    tools = {row.get("observation_id"): row.get("tool_name") for row in observations if row.get("ok") is True}
    verified = {ref for gap in state.gaps if gap.state == "resolved" and gap.support == "checked" and gap.check
                for ref in gap.evidence_refs if tools.get(ref) == gap.check.tool_name}
    if not set(refs).issubset(verified):
        raise ValueError("Partial delivery evidence must come from checked Goal Gaps. Trial results and blockers are not verified deliverables.")


def validate_user_dependency(state: GoalGapState, value: Any, observations: list[dict], *, input_kind: str) -> None:
    if not isinstance(value, dict):
        raise ValueError("Specify user_dependency: what only the user can supply, decide, or do.")
    dependency = UserDependency.model_validate(value)
    if not dependency.reason.strip():
        raise ValueError("The user dependency needs a concrete reason.")
    unresolved = {gap.id for gap in state.gaps if gap.state != "resolved"}
    if not set(dependency.gap_ids).issubset(unresolved) or (state.gaps and not dependency.gap_ids):
        raise ValueError("The user dependency must identify at least one current unresolved gap when gaps are tracked.")
    facts = {item.get("observation_id"): item for item in observations}
    if any(ref not in facts for ref in dependency.evidence_refs):
        raise ValueError("User dependency evidence must reference current Runtime observations.")
    if dependency.kind == "user_information" and input_kind != "text":
        raise ValueError("Request text for information that only the user can provide.")
    if dependency.kind == "human_action" and not any(
        facts[ref].get("tool_name") != "runtime.user_input"
        and (facts[ref].get("error") or {}).get("category") not in _NON_GOAL_CATEGORIES
        for ref in dependency.evidence_refs
    ):
        raise ValueError("A human-only action needs a Runtime observation showing why it is necessary.")


def answer_disposition(state: GoalGapState, *, blocked: bool, observations: list[dict]) -> str | None:
    unresolved = [gap for gap in state.gaps if gap.state != "resolved"]
    if blocked:
        if unresolved and all(gap.state == "blocked" and gap.evidence_refs for gap in unresolved):
            return "goal_blocked"
        if not state.gaps and any(not item.get("ok") and (item.get("error") or {}).get("category")
                                  not in _NON_GOAL_CATEGORIES for item in observations):
            return "goal_blocked"
        raise ValueError("A blocked report requires observed blockers for every remaining gap.")
    if unresolved:
        pending = {gap.id for gap in unresolved}
        ready = [gap.id for gap in unresolved if not pending.intersection(gap.depends_on)]
        raise ValueError("The answer cannot complete. Verify prerequisite gaps first: " + ", ".join(ready))
    return None


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
    settled = [item for item in observations if (item.get("error") or {}).get("category") not in _NON_GOAL_CATEGORIES]
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
    if trial and new_evidence and not result.gaps:
        result.recovery.mode = "execute"
        result.recovery.reason = ""
        result.recovery.evidence_refs = []
        result.recovery.decision = None
        result.recovery.proposal = ""
        result.recovery.rejections = result.recovery.failed_trials = 0
        result.recent = []
    # With a tracked goal, only an accepted check can clear Recovery.
    result.recent = [*result.recent, GapFrame(signature=signature, outcome=outcome, failures=failures[:16])][-window:]
    recent = result.recent
    stalled = len(recent) == window and not any(frame.progress for frame in recent) and len({frame.signature for frame in recent}) < len(recent)
    repeated_failure = bool(failures and any(key in frame.failures for frame in recent[:-1] for key in failures))
    if trial and (not new_evidence or result.gaps):
        repeated_trial = any(frame.signature == signature or (not failures and frame.outcome == outcome)
                             for frame in recent[:-1])
        result.recovery.failed_trials = result.recovery.failed_trials + 1 if repeated_trial else 0
        _reassess(result, "recovery_pending_goal_verification" if new_evidence else "recovery_produced_no_new_evidence",
                  [item["observation_id"] for item in settled if not failures or not item.get("ok")])
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
        if diagnostic and not repeated:
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
            control.rejections = 0
            for row in repeated:
                row.retries += 1
    if error:
        control.rejections += 1
        control.decision = None
    if result.model_dump() != state.model_dump():
        result.revision += 1
    return result, error


def gap_projection(state: GoalGapState, *, context_chars: int = 2400, window: int = 4, feedback: str = "", observations: list[dict] | None = None, objective: str = "", advisory_recovery: bool = False) -> dict:
    unresolved = [gap for gap in state.gaps if gap.state != "resolved"]
    visible = [*unresolved, *[gap for gap in state.gaps if gap.state == "resolved"]]
    recent = state.recent[-window:]
    stalled = len(recent) == window and not any(frame.progress for frame in recent) and len({frame.signature for frame in recent}) < len(recent)
    projection = {"revision": state.revision, "focus": state.focus, "summary": gap_outcome(state),
                  "gaps": [{"id": gap.id, "kind": gap.kind, "state": gap.state, "support": gap.support,
                            **({"depends_on": gap.depends_on} if gap.depends_on else {}),
                            "requirement": gap.requirement[:96 if gap.state != "resolved" else 32]} for gap in visible]}
    candidates = sorted(unresolved, key=lambda gap: gap.id not in state.focus)
    checks = {gap.id: gap.check.model_dump(exclude_defaults=True) for gap in candidates if gap.check is not None}
    if checks:
        projection["focus_checks"] = checks
    if stalled or state.recovery.mode == "reassess":
        projection["recovery"] = "Repeated execution without accepted progress. Reconsider the unresolved gap: change evidence or method, clarify, or report blocked. Keep all safety/approval constraints."
        projection["execution_control"] = {"mode": "reassess", "reason": state.recovery.reason,
            "evidence_refs": state.recovery.evidence_refs,
            "required": "New read-only investigations can run; other calls require gap_update.recovery. User waits and answers are checked against open gaps."}
        if advisory_recovery:
            projection["recovery"] = "Runtime detected an execution pattern, not a verdict on goal progress. Decide whether to change course."
            projection["execution_control"]["required"] = (
                "Fresh registered read-only or workspace actions do not need a recovery decision; normal authorization, "
                "failed-call replay guards and higher-risk recovery requirements still apply.")
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
    beliefs = [row.model_dump() for row in sorted(reversed(state.beliefs), key=lambda row: row.gap_id not in state.focus)]
    if beliefs:
        projection["candidate_beliefs"] = beliefs
    if objective and visible:
        projection["user_objective"] = objective[:360]
        refs = {ref for gap in visible for ref in gap.evidence_refs}
        refs.update(ref for row in state.beliefs for ref in row.evidence_refs)
        linked = [{"id": row["observation_id"], "tool": row.get("tool_name"), "ok": row.get("ok"),
                   "gap_ids": [gap.id for gap in visible if row["observation_id"] in gap.evidence_refs]}
                  for row in reversed(observations or []) if row.get("observation_id") in refs][:6]
        if linked:
            projection["linked_evidence"] = linked
        while linked and len(json.dumps(projection, ensure_ascii=False)) > context_chars:
            linked.pop()
        if not linked:
            projection.pop("linked_evidence", None)
        if len(json.dumps(projection, ensure_ascii=False)) > context_chars:
            projection.pop("user_objective", None)
    while len(json.dumps(projection, ensure_ascii=False)) > context_chars and beliefs:
        beliefs.pop()
    if not beliefs:
        projection.pop("candidate_beliefs", None)
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
