from unittest.mock import MagicMock

import asyncio

import pytest

from gateway.events import EventEmitter
from gateway.models import RunContext, SessionState
from gateway.protocol import EventType
from gateway.security.audit import SecurityAuditService
from gateway.tool_service import ToolPolicyViolationError, ToolService, ToolInvocationContext
from gateway.workspace_service import WorkspaceService, WorkspaceSandboxError


def _build_run_context(user_id: str = "u1") -> RunContext:
    state = SessionState(session_id="s1", user_id=user_id, trace_id="t1", reasoning_mode="deep")
    return RunContext(
        request_id="r1",
        trace_id="t1",
        session_state=state,
        tool_policy={"allow": {"*"}},
    )


@pytest.mark.asyncio
async def test_security_boundary_event_is_collected_in_audit_report():
    emitter = EventEmitter()
    await emitter.emit(
        EventType.SECURITY_BOUNDARY_VIOLATION,
        {
            "trace_id": "t1",
            "request_id": "r1",
            "session_id": "s1",
            "user_id": "u1",
            "namespace": "memory",
            "reason": "cross_user_memory_access",
            "outcome": "blocked",
        },
    )

    report = SecurityAuditService(emitter).build_report(user_id="u1", limit=50)
    assert report["summary"]["namespace_violations"] >= 1
    assert report["violations"][0]["action"] == "namespace_violation_attempt"


@pytest.mark.asyncio
async def test_workspace_cross_user_access_blocked_and_audited(tmp_path):
    emitter = EventEmitter()
    service = WorkspaceService(event_emitter=emitter, base_dir=str(tmp_path))
    owner_handle = service.resolve_workspace_handle(user_id="owner", workspace_id="w1")

    with pytest.raises(WorkspaceSandboxError):
        service.create_document(
            handle=owner_handle,
            relative_path="note.txt",
            content="x",
            requester_user_id="attacker",
            trace_id="t2",
            request_id="r2",
            session_id="s2",
        )

    # emit is async fire-and-forget; give event loop one tick
    await asyncio.sleep(0)
    audits = emitter.get_audit_history(action="namespace_violation_attempt")
    assert audits
    assert audits[-1].details.get("namespace") == "workspace"


@pytest.mark.asyncio
async def test_tool_cross_user_access_blocked_and_audited():
    emitter = EventEmitter()
    service = ToolService(event_emitter=emitter, mcp_manager=MagicMock())

    class _AnyTool:
        tool_id = "local.any"
        name = "Any"
        description = "any"

        async def invoke(self, args, ctx=None):
            return {"ok": True}

    service.register_tool(_AnyTool())

    with pytest.raises(ToolPolicyViolationError):
        await service.call_tool(
            "local.any",
            {"x": 1},
            ctx=ToolInvocationContext(session_id="s1", user_id="u2", source="chat"),
            request_id="r3",
            run_context=_build_run_context(user_id="u1"),
        )

    audits = emitter.get_audit_history(action="namespace_violation_attempt")
    assert audits
    assert audits[-1].details.get("namespace") == "tool"


@pytest.mark.asyncio
async def test_secret_access_event_included_in_security_report():
    emitter = EventEmitter()
    await emitter.emit(
        EventType.SECURITY_SECRET_ACCESS,
        {
            "trace_id": "t9",
            "request_id": "r9",
            "session_id": "s9",
            "user_id": "u9",
            "namespace": "config",
            "secret_field": "api.api_key",
            "outcome": "blocked",
        },
    )

    report = SecurityAuditService(emitter).build_report(user_id="u9", limit=20)
    assert report["summary"]["secret_access_events"] == 1

