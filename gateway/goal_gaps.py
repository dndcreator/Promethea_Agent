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


class GapDelta(GapContract):
    revision: StrictInt = Field(ge=0)
    create: list[GapSpec] = Field(default_factory=list, max_length=8)
    updates: list[GapChange] = Field(default_factory=list, max_length=8)
    focus: list[str] | None = Field(default=None, max_length=4)


class GoalGap(GapSpec):
    declared_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    state: Literal["open", "blocked", "resolved"] = "open"
    support: Literal["none", "inferred", "checked"] = "none"
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)


class GapFrame(GapContract):
    signature: str
    progress: bool = False


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


def observe_gap_step(state: GoalGapState, path: list[dict], observations: list[dict], *, window: int = 4) -> GoalGapState:
    if not state.gaps or not any(gap.state == "open" for gap in state.gaps):
        return state
    settled = [item for item in observations if (item.get("error") or {}).get("category") != "approval"]
    if not settled:
        return state
    ids = {item["tool_call_id"] for item in settled}
    calls = [{"tool": item.get("tool_name"), "args": item.get("args")} for item in path if item.get("tool_call_id") in ids]
    facts = [{"tool": item.get("tool_name"), "ok": item.get("ok"),
              "result": item.get("structured_result") if item.get("structured_result") is not None else item.get("model_projection"),
              "error": item.get("error")} for item in settled]
    result = state.model_copy(deep=True)
    try:
        signature = fingerprint({"focus": sorted(result.focus), "calls": calls, "facts": facts})
    except (TypeError, ValueError):
        # Monitoring must not turn an unusual tool payload into a failed action.
        return state
    # A changed result is only an anti-repetition signal, not verified goal progress.
    result.recent = [*result.recent, GapFrame(signature=signature)][-window:]
    result.revision += 1
    return result


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
    if stalled:
        projection["recovery"] = "Repeated execution without accepted progress. Reconsider the unresolved gap: change evidence or method, clarify, or report blocked. Keep all safety/approval constraints."
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
