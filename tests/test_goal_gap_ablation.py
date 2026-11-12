"""Paired Goal Gap profiles with the same tool, approval and delivery contracts."""
from types import SimpleNamespace

import pytest

from gateway.action import ActionService
from gateway.tool_prompt_blocks import build_action_protocol_prompt
from gateway.tools.registry import ToolRegistry
from tests.support.runtime import goal_context, observation_fact
from tests.test_goal_gaps import Core
from tests.test_action_progress_control import closed, recovery, tool


PROFILES = ((False, False), (True, False), (False, True), (True, True))
GOAL = "Recover the exact release label and verify the saved result. Try fixture.primary first. If unavailable, investigate a backup."
SPEC = {"id": "artifact", "kind": "achievement", "requirement": "Verify the saved release label",
        "check": {"tool_name": "fixture.verify", "pointer": "/valid", "expected": True}}


async def trial(core, semantic, advisory, *, deny_workspace=False):
    registry = ToolRegistry()
    for name, level in (("primary", "read_only"), ("stage_backup", "workspace_write"), ("verify", "read_only")):
        registry.register_local_tool(SimpleNamespace(tool_id=f"fixture.{name}", side_effect_level=level))
    dispatches, approvals, artifact = [], [], {}

    def execute(name, args):
        dispatches.append(name)
        if name == "fixture.primary":
            return closed(name)
        if name == "fixture.stage_backup":
            artifact["label"] = "ORCHID-29"
            return {"label": artifact["label"]}
        if name == "fixture.verify":
            return {"valid": artifact.get("label") == "ORCHID-29"}
        raise ValueError("unknown fixture tool")

    def approval(name, _args):
        approvals.append(name)
        return deny_workspace and name == "fixture.stage_backup"

    service = ActionService(conversation_core=core, capability_service=SimpleNamespace(tool_registry=registry))
    result = await service.run_action(goal=GOAL, budget=7, messages=[
        {"role": "system", "content": build_action_protocol_prompt()},
        {"role": "user", "content": GOAL + " Available tools (all take {}): fixture.primary reads the primary source; "
         "fixture.stage_backup recovers the label and stages it in the isolated workspace; fixture.verify checks the "
         "staged label against the authoritative record, returning {valid: boolean}. Report the exact label only if verified."},
    ], user_config={"api": {"tool_protocol": "prompt_json", "max_tokens": 8192}, "action": {"gaps": {
        "semantic_context": semantic, **({} if advisory is None else {"advisory_recovery": advisory})}}},
        tool_executor=execute, confirmation_resolver=approval)
    verified = (result.get("goal_progress") or {}).get("checks_passed", 0)
    return {"verified_delivery": verified == 1 and artifact.get("label") == "ORCHID-29"
            and "ORCHID-29" in result.get("content", "") and not result.get("execution_outcome"),
            "artifact": artifact, "status": result["status"], "dispatches": dispatches, "approvals": approvals,
            "recovery_denials": sum((o.get("error") or {}).get("code") == "ACTION_REASSESSMENT_REQUIRED"
                                    for o in result.get("observations", []))}


@pytest.mark.asyncio
@pytest.mark.parametrize("semantic,advisory", PROFILES)
async def test_paired_profiles(semantic, advisory):
    def backup(messages):
        assert ("user_objective" in goal_context(messages)) is semantic
        return tool("fixture.stage_backup")

    def recover_or_verify(messages):
        if advisory:
            return tool("fixture.verify")
        assert observation_fact(messages)["error"]["code"] == "ACTION_REASSESSMENT_REQUIRED"
        return recovery(messages, name="fixture.stage_backup")

    def finish(messages):
        return {"action": "answer", "content": "Verified ORCHID-29", "gap_update": {
            "revision": goal_context(messages)["revision"], "updates": [
                {"id": "artifact", "state": "resolved", "evidence_refs": [observation_fact(messages)["observation_id"]]}]}}

    responses = [{**tool("fixture.primary"), "gap_update": {"revision": 0, "create": [SPEC]}},
                 backup, recover_or_verify, *([] if advisory else [tool("fixture.verify")]), finish]
    core = Core(responses)
    out = await trial(core, semantic, advisory)
    assert out["verified_delivery"]
    assert out["dispatches"] == ["fixture.primary", "fixture.stage_backup", "fixture.verify"]
    assert out["recovery_denials"] == int(not advisory)
    assert len(core.calls) == (4 if advisory else 5)


@pytest.mark.asyncio
async def test_advisory_profile_does_not_grant_workspace_approval():
    core = Core([tool("fixture.primary"), tool("fixture.stage_backup")])
    out = await trial(core, False, None, deny_workspace=True)
    assert out["status"] == "needs_confirmation"
    assert out["dispatches"] == ["fixture.primary"] and out["artifact"] == {}
