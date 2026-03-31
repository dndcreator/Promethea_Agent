from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from gateway.protocol import RequestType
from gateway.server import GatewayServer
from gateway.tool_service import ToolService
from gateway.workflow_engine import WorkflowEngine
from gateway.workspace_service import WorkspaceService


class _EchoTool:
    tool_id = "utils.echo"
    name = "utils.echo"
    description = "Echo input text."

    async def invoke(self, args, ctx=None):
        _ = ctx
        return {"echo": str((args or {}).get("text") or "")}


class _InMemoryMessageManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.turns: Dict[str, Dict[str, Any]] = {}
        self.pending: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _k(user_id: Optional[str], session_id: str) -> str:
        return f"{user_id or 'default'}::{session_id}"

    def get_session(self, session_id: str, user_id: Optional[str] = None):
        return self.sessions.get(self._k(user_id, session_id))

    def create_session(self, session_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
        sid = session_id or f"s_{uuid.uuid4().hex[:8]}"
        self.sessions[self._k(user_id, sid)] = {"session_id": sid, "user_id": user_id, "messages": []}
        return sid

    def begin_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_role: str,
        user_content: str,
        user_id: Optional[str] = None,
    ) -> bool:
        key = self._k(user_id, session_id)
        if key not in self.sessions:
            self.create_session(session_id=session_id, user_id=user_id)
        self.turns[turn_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "user_role": user_role,
            "user_content": user_content,
        }
        return True

    def commit_turn(
        self,
        session_id: str,
        turn_id: str,
        assistant_content: str,
        user_id: Optional[str] = None,
    ) -> bool:
        key = self._k(user_id, session_id)
        sess = self.sessions.get(key)
        if not sess:
            return False
        sess["messages"].append({"role": "assistant", "content": assistant_content, "turn_id": turn_id})
        self.turns.pop(turn_id, None)
        return True

    def abort_turn(self, session_id: str, turn_id: str, user_id: Optional[str] = None) -> bool:
        _ = (session_id, user_id)
        self.turns.pop(turn_id, None)
        return True

    def set_pending_confirmation(self, session_id: str, payload: Dict[str, Any], user_id: Optional[str] = None) -> None:
        self.pending[self._k(user_id, session_id)] = dict(payload or {})

    def get_pending_confirmation(self, session_id: str, user_id: Optional[str] = None):
        return self.pending.get(self._k(user_id, session_id))

    def clear_pending_confirmation(self, session_id: str, user_id: Optional[str] = None) -> None:
        self.pending.pop(self._k(user_id, session_id), None)

    def get_recent_messages(self, session_id: str, count: int = 6, user_id: Optional[str] = None):
        sess = self.sessions.get(self._k(user_id, session_id)) or {}
        messages = list(sess.get("messages") or [])
        return messages[-max(1, int(count)) :]


class _FlowConversationService:
    def __init__(self) -> None:
        self.run_calls: List[Any] = []

    async def prepare_chat_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message: str,
        channel: str,
        include_recent: bool,
        run_context: Any = None,
    ):
        _ = (include_recent, run_context)
        return {
            "messages": [{"role": "user", "content": user_message}],
            "user_config": {"channel": channel, "user_id": user_id},
            "reasoning": {},
        }

    async def run_conversation(self, conversation_input):
        self.run_calls.append(conversation_input)
        if len(self.run_calls) == 1:
            return {
                "status": "needs_confirmation",
                "tool_call_id": "tc_plus",
                "tool_name": "filesystem.write_file",
                "args": {"path": "reports/business-plus.md", "content": "plus-report"},
                "pending_tool_calls": [
                    {
                        "name": "filesystem.write_file",
                        "args": {"path": "reports/business-plus.md", "content": "plus-report"},
                        "id": "tc_plus",
                    }
                ],
                "content": "Approval needed before writing business-plus report.",
            }
        return {
            "status": "success",
            "content": "Business-plus report written.",
        }


@pytest.mark.asyncio
async def test_business_plus_chat_confirmation_roundtrip(monkeypatch):
    server = GatewayServer()
    server.message_manager = _InMemoryMessageManager()
    server.conversation_service = _FlowConversationService()
    server.mcp_manager = object()

    async def _fake_execute_tool_calls(*args, **kwargs):
        _ = (args, kwargs)
        return [{"type": "text", "text": "tool execution ok: reports/business-plus.md"}]

    monkeypatch.setattr("gateway.server.execute_tool_calls", _fake_execute_tool_calls)

    first = await server.handle_http_request(
        method=RequestType.CHAT,
        params={"message": "请写业务日报并保存"},
        user_id="u_plus",
    )
    assert first.ok is True
    assert first.payload["status"] == "needs_confirmation"
    session_id = str(first.payload["session_id"])
    assert server.message_manager.get_pending_confirmation(session_id, user_id="u_plus") is not None

    second = await server.handle_http_request(
        method=RequestType.CHAT_CONFIRM,
        params={"session_id": session_id, "tool_call_id": "tc_plus", "action": "approve"},
        user_id="u_plus",
    )
    assert second.ok is True
    assert second.payload["status"] == "success"
    assert "report written" in str(second.payload.get("response") or "").lower()
    assert server.message_manager.get_pending_confirmation(session_id, user_id="u_plus") is None


@pytest.mark.asyncio
async def test_business_plus_workflow_pause_approve_resume(tmp_path: Path):
    server = GatewayServer()
    workspace = WorkspaceService(base_dir=str(tmp_path / "workspace"))
    engine = WorkflowEngine(workspace_service=workspace)
    server.workspace_service = workspace
    server.workflow_engine = engine

    defined = await server.handle_http_request(
        method=RequestType.WORKFLOW_DEFINE,
        params={
            "workflow_id": "wf.business.plus.approval",
            "name": "Business Plus Approval",
            "workflow_type": "linear",
            "steps": [
                {"step_id": "s1", "step_type": "approval_step", "name": "审批确认"},
                {
                    "step_id": "s2",
                    "step_type": "artifact_step",
                    "name": "写入产物",
                    "depends_on": ["s1"],
                    "inputs": {"path": "reports/approved.md", "content": "approved"},
                },
            ],
        },
        user_id="u_plus",
    )
    assert defined.ok is True

    started = await server.handle_http_request(
        method=RequestType.WORKFLOW_START,
        params={"workflow_id": "wf.business.plus.approval", "session_id": "s_plus", "workspace_id": "w_plus"},
        user_id="u_plus",
    )
    assert started.ok is True
    run_id = started.payload["run"]["workflow_run_id"]
    assert started.payload["run"]["status"] == "waiting_human"

    paused = await server.handle_http_request(
        method=RequestType.WORKFLOW_PAUSE,
        params={"workflow_run_id": run_id},
        user_id="u_plus",
    )
    assert paused.ok is True
    assert paused.payload["run"]["status"] == "paused"

    approved = await server.handle_http_request(
        method=RequestType.WORKFLOW_APPROVE_STEP,
        params={"workflow_run_id": run_id, "step_id": "s1"},
        user_id="u_plus",
    )
    assert approved.ok is True

    resumed = await server.handle_http_request(
        method=RequestType.WORKFLOW_RESUME,
        params={"workflow_run_id": run_id},
        user_id="u_plus",
    )
    assert resumed.ok is True
    assert resumed.payload["run"]["status"] == "completed"

    artifacts = await server.handle_http_request(
        method=RequestType.WORKSPACE_LIST_ARTIFACTS,
        params={"workspace_id": "w_plus", "session_id": "s_plus", "subdir": "reports"},
        user_id="u_plus",
    )
    assert artifacts.ok is True
    assert any(item.get("path") == "reports/approved.md" for item in (artifacts.payload.get("artifacts") or []))


@pytest.mark.asyncio
async def test_business_plus_batch_tool_and_workflow_visibility(tmp_path: Path):
    server = GatewayServer()
    workspace = WorkspaceService(base_dir=str(tmp_path / "workspace"))
    engine = WorkflowEngine(workspace_service=workspace)
    tools = ToolService(event_emitter=None)
    tools.register_tool(_EchoTool())
    server.workspace_service = workspace
    server.workflow_engine = engine
    server.tool_service = tools

    define = await server.handle_http_request(
        method=RequestType.WORKFLOW_DEFINE,
        params={
            "workflow_id": "wf.plus.batch",
            "name": "Plus Batch",
            "workflow_type": "linear",
            "steps": [{"step_id": "s1", "step_type": "artifact_step", "name": "w", "inputs": {"path": "x.md", "content": "x"}}],
        },
        user_id="u_plus_batch",
    )
    assert define.ok is True

    batch = await server.handle_http_request(
        method=RequestType.BATCH,
        params={
            "requests": [
                {"method": RequestType.TOOLS_LIST.value, "params": {"requested_mode": "react_tot"}, "priority": 3},
                {"method": RequestType.TOOL_CALL.value, "params": {"tool_name": "utils.echo", "params": {"text": "plus"}}, "priority": 2},
                {"method": RequestType.WORKFLOW_LIST.value, "params": {"owner_user_id": "u_plus_batch"}, "priority": 1},
            ]
        },
        user_id="u_plus_batch",
    )
    assert batch.ok is True
    results = batch.payload.get("results") or []
    assert len(results) == 3
    by_method = {row["method"]: row for row in results}
    assert by_method[RequestType.TOOLS_LIST.value]["ok"] is True
    assert by_method[RequestType.TOOL_CALL.value]["ok"] is True
    assert by_method[RequestType.TOOL_CALL.value]["payload"]["result"]["echo"] == "plus"
    assert by_method[RequestType.WORKFLOW_LIST.value]["ok"] is True
    assert any(item.get("workflow_id") == "wf.plus.batch" for item in by_method[RequestType.WORKFLOW_LIST.value]["payload"]["workflows"])
