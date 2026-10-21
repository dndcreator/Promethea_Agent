"""Public HTTP/SSE -> Conversation -> Action -> Task, with a deterministic model."""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.action import ActionService
from gateway.conversation_service import ConversationService
from gateway.http import message_manager as message_module
from gateway.http.routes import chat, task
from gateway.http.routes.auth import get_current_user_id
from gateway.http.session_store import SessionStorage
from gateway.server_runtime_utils import build_run_context
from gateway.task_service import TaskService
from core import services as core_services


class Model:
    def __init__(self):
        self.calls = []

    async def call_llm(self, messages, **kwargs):
        self.calls.append(messages)
        if len(self.calls) == 1:
            action = {"action": "tool_call", "tool_name": "export.validate", "args": {}, "gap_update": {
                "revision": 0, "create": [{"id": "export", "kind": "achievement", "requirement": "Export is valid",
                                          "check": {"tool_name": "export.validate", "pointer": "/valid", "expected": True}}]}}
        elif len(self.calls) == 2:
            observation = json.loads(messages[-1]["content"][0]["text"])
            system = next(item["content"] for item in messages if item["role"] == "system")
            revision = json.loads(system.split("\n")[-1])["revision"]
            action = {"action": "answer", "content": "Export validated", "gap_update": {
                "revision": revision, "updates": [{"id": "export", "state": "resolved", "evidence_refs": [observation["observation_id"]]}]}}
        else:
            action = {"action": "answer", "content": "Previous export is retained"}
        return {"status": "success", "content": json.dumps(action)}


def test_task_bound_sse_and_public_query_survive_restart_without_private_state(tmp_path, monkeypatch):
    path = str(tmp_path / "tasks.json")
    tasks = TaskService(storage_path=path)
    monkeypatch.setattr(core_services, "get_memory_service", lambda: None)
    monkeypatch.setattr(message_module, "SessionStorage", lambda: SessionStorage(str(tmp_path / "sessions.json")))
    messages = message_module.MessageManager()
    messages.memory_adapter = None
    model = Model()
    action = ActionService(conversation_core=model, task_service=tasks)
    conversation = ConversationService(conversation_core=model, action_service=action)

    async def prepare(**kwargs):
        return {"messages": [{"role": "user", "content": kwargs["user_message"]}], "reasoning": {}, "user_config": {}}

    conversation.prepare_chat_turn = prepare
    executed = []

    async def execute(name, args, **kwargs):
        executed.append(name)
        return {"valid": True}

    server = SimpleNamespace(message_manager=messages, conversation_service=conversation,
                             task_service=tasks, reasoning_service=None, config_service=None, event_emitter=None,
                             _build_run_context=build_run_context, _apply_skill_runtime_context=lambda **_: None,
                             _execute_tool_for_chat=execute)
    monkeypatch.setattr(chat, "get_gateway_server", lambda: server)
    monkeypatch.setattr(task, "get_gateway_server", lambda: server)
    app = FastAPI()
    app.include_router(chat.router)
    app.include_router(task.router)
    app.dependency_overrides[get_current_user_id] = lambda: "alice"
    with TestClient(app) as client:
        task_id = client.post("/tasks", json={"title": "Export", "objective": "Export a valid document"}).json()["task"]["task_id"]
        response = client.post("/chat", json={"message": "Export", "session_id": "s1", "task_id": task_id, "stream": True})
        assert response.status_code == 200 and "Export validated" in response.text
        assert '"task_id": "' + task_id + '"' in response.text
        assert 'event: error' not in response.text
        assert len(model.calls) == 2 and executed == ["export.validate"]
        public = client.get(f"/tasks/{task_id}").json()["task"]["goal_gaps"]
        assert public["gaps"][0]["support"] == "checked"
        assert "barriers" not in public and "recent" not in public

        restored = TaskService(storage_path=path)
        server.task_service = action.task_service = restored
        response = client.post("/chat", json={"message": "Continue", "session_id": "s1", "task_id": task_id, "stream": True})
        assert "Previous export is retained" in response.text
        assert '"state":"resolved"' in str(model.calls[-1])
        assert len(executed) == 1

        app.dependency_overrides[get_current_user_id] = lambda: "bob"
        assert client.get(f"/tasks/{task_id}").status_code == 404
        denied = client.post("/chat", json={"message": "Continue", "task_id": task_id, "stream": True})
        assert "event: error" in denied.text and len(model.calls) == 3
