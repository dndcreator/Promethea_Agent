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
                "tool_call_id": "tc_1",
                "tool_name": "filesystem.write_file",
                "args": {"path": "reports/today.md", "content": "daily-report"},
                "pending_tool_calls": [
                    {
                        "name": "filesystem.write_file",
                        "args": {"path": "reports/today.md", "content": "daily-report"},
                        "id": "tc_1",
                    }
                ],
                "content": "I can write this report to workspace if you approve.",
            }
        return {
            "status": "success",
            "content": "Report written. You can find it at reports/today.md.",
        }


@pytest.mark.asyncio
async def test_business_journey_chat_confirmation_then_resume(monkeypatch):
    server = GatewayServer()
    server.message_manager = _InMemoryMessageManager()
    server.conversation_service = _FlowConversationService()
    server.mcp_manager = object()

    async def _fake_execute_tool_calls(*args, **kwargs):
        _ = (args, kwargs)
        return [{"type": "text", "text": "tool execution ok: reports/today.md"}]

    monkeypatch.setattr("gateway.server.execute_tool_calls", _fake_execute_tool_calls)

    first = await server.handle_http_request(
        method=RequestType.CHAT,
        params={"message": "请帮我生成日报并写入文件"},
        user_id="u_biz",
    )
    assert first.ok is True
    assert first.payload["status"] == "needs_confirmation"
    assert first.payload["tool_call_id"] == "tc_1"
    session_id = str(first.payload["session_id"])
    assert server.message_manager.get_pending_confirmation(session_id, user_id="u_biz") is not None

    second = await server.handle_http_request(
        method=RequestType.CHAT_CONFIRM,
        params={
            "session_id": session_id,
            "tool_call_id": "tc_1",
            "action": "approve",
        },
        user_id="u_biz",
    )
    assert second.ok is True
    assert second.payload["status"] == "success"
    assert "reports/today.md" in str(second.payload.get("response") or "")
    assert server.message_manager.get_pending_confirmation(session_id, user_id="u_biz") is None


@pytest.mark.asyncio
async def test_business_journey_batch_define_start_and_verify_workflow_artifact(tmp_path: Path):
    server = GatewayServer()
    workspace = WorkspaceService(base_dir=str(tmp_path / "workspace"))
    engine = WorkflowEngine(workspace_service=workspace)
    server.workspace_service = workspace
    server.workflow_engine = engine

    batch = await server.handle_http_request(
        method=RequestType.BATCH,
        params={
            "requests": [
                {
                    "method": RequestType.WORKFLOW_DEFINE.value,
                    "params": {
                        "workflow_id": "wf.daily.report",
                        "name": "Daily Report",
                        "workflow_type": "linear",
                        "steps": [
                            {
                                "step_id": "write_report",
                                "step_type": "artifact_step",
                                "name": "Write Report",
                                "inputs": {"path": "reports/daily.md", "content": "day-1"},
                            }
                        ],
                    },
                    "priority": 3,
                },
                {
                    "method": RequestType.WORKFLOW_START.value,
                    "params": {
                        "workflow_id": "wf.daily.report",
                        "session_id": "s_daily",
                        "workspace_id": "w_daily",
                    },
                    "priority": 2,
                },
                {
                    "method": RequestType.WORKSPACE_LIST_ARTIFACTS.value,
                    "params": {
                        "workspace_id": "w_daily",
                        "session_id": "s_daily",
                        "subdir": "reports",
                    },
                    "priority": 1,
                },
            ]
        },
        user_id="u_batch",
    )

    assert batch.ok is True
    results = batch.payload.get("results") or []
    assert len(results) == 3
    by_method = {row["method"]: row for row in results}
    assert by_method[RequestType.WORKFLOW_DEFINE.value]["ok"] is True
    assert by_method[RequestType.WORKFLOW_START.value]["ok"] is True
    run_payload = by_method[RequestType.WORKFLOW_START.value]["payload"]["run"]
    assert run_payload["status"] == "completed"

    assert by_method[RequestType.WORKSPACE_LIST_ARTIFACTS.value]["ok"] is True
    artifacts = by_method[RequestType.WORKSPACE_LIST_ARTIFACTS.value]["payload"]["artifacts"]
    assert any(item.get("path") == "reports/daily.md" for item in artifacts)


@pytest.mark.asyncio
async def test_business_journey_toolbox_discovery_then_call():
    server = GatewayServer()
    tools = ToolService(event_emitter=None)
    tools.register_tool(_EchoTool())
    server.tool_service = tools

    listing = await server.handle_http_request(
        method=RequestType.TOOLS_LIST,
        params={"requested_mode": "react_tot"},
        user_id="u_tools",
    )
    assert listing.ok is True
    catalog = listing.payload.get("catalog") or []
    target = next((row for row in catalog if row.get("service_name") == "utils.echo"), None)
    assert target is not None
    assert target["callable_now"] is True

    called = await server.handle_http_request(
        method=RequestType.TOOL_CALL,
        params={"tool_name": "utils.echo", "params": {"text": "hello-toolbox"}},
        user_id="u_tools",
    )
    assert called.ok is True
    assert called.payload["result"]["echo"] == "hello-toolbox"
