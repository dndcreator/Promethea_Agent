from unittest.mock import MagicMock

import pytest

from gateway.events import EventEmitter
from gateway.models import RunContext, SessionState
from gateway.observability.audit import AuditEvent
from gateway.observability.trace import TraceEvent
from gateway.protocol import EventType
from gateway.tool_service import ToolInvocationContext, ToolService


def _build_run_context() -> RunContext:
    state = SessionState(session_id="s1", user_id="u1", trace_id="t1", reasoning_mode="deep")
    return RunContext(
        request_id="r1",
        trace_id="t1",
        session_state=state,
        tool_policy={"allow": {"local.write_file"}},
    )


def test_trace_event_model_serialization():
    event = TraceEvent(
        trace_id="t1",
        request_id="r1",
        session_id="s1",
        user_id="u1",
        event_type="gateway.run.started",
        payload={"k": "v"},
        seq=1,
    )
    dumped = event.model_dump()
    assert dumped["trace_id"] == "t1"
    assert dumped["event_type"] == "gateway.run.started"


def test_audit_event_model_serialization():
    event = AuditEvent(
        trace_id="t1",
        request_id="r1",
        session_id="s1",
        user_id="u1",
        event_type="tool.call.start",
        action="side_effect_tool_execution",
        outcome="attempted",
        details={"tool_name": "local.write_file"},
    )
    dumped = event.model_dump()
    assert dumped["action"] == "side_effect_tool_execution"
    assert dumped["outcome"] == "attempted"


@pytest.mark.asyncio
async def test_main_path_trace_fields_completeness():
    emitter = EventEmitter()
    await emitter.emit(
        EventType.GATEWAY_RUN_STARTED,
        {
            "trace_id": "t1",
            "request_id": "r1",
            "session_id": "s1",
            "user_id": "u1",
            "source_module": "gateway.server",
        },
    )

    traces = emitter.get_trace_history(trace_id="t1")
    assert traces
    latest = traces[-1]
    assert latest.trace_id == "t1"
    assert latest.request_id == "r1"
    assert latest.session_id == "s1"
    assert latest.user_id == "u1"


@pytest.mark.asyncio
async def test_side_effect_tool_generates_audit_event():
    emitter = EventEmitter()
    service = ToolService(event_emitter=emitter, mcp_manager=MagicMock())

    class _WriteTool:
        tool_id = "local.write_file"
        name = "Write"
        description = "write file"

        async def invoke(self, args, ctx=None):
            return {"ok": True}

    service.register_tool(_WriteTool())
    run_context = _build_run_context()

    await service.call_tool(
        "local.write_file",
        {"path": "a.txt", "content": "x"},
        ctx=ToolInvocationContext(session_id="s1", user_id="u1", source="chat"),
        request_id="r1",
        run_context=run_context,
    )

    audits = emitter.get_audit_history(action="side_effect_tool_execution")
    assert audits
    assert audits[-1].trace_id == "t1"


@pytest.mark.asyncio
async def test_memory_write_decision_generates_audit_event():
    emitter = EventEmitter()
    await emitter.emit(
        EventType.MEMORY_WRITE_DECIDED,
        {
            "trace_id": "t1",
            "request_id": "r1",
            "session_id": "s1",
            "user_id": "u1",
            "decision": "write",
            "source_module": "gateway.server",
        },
    )

    audits = emitter.get_audit_history(action="memory_write_decision")
    assert audits
    assert audits[-1].outcome == "write"
