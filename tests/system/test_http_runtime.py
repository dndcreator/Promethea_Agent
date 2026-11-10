"""Real HTTP routes, JWT login, Gateway and disk effects with scripted model I/O.

This is in-process system acceptance, not full launcher/browser/provider E2E.
"""
from pathlib import Path
import json
import pytest

from fastapi.testclient import TestClient
from gateway.http.routes import auth
from tests.support.runtime import ScriptedModel, finish_from_observation, runtime_at
from tests.support.http_runtime import app_at


@pytest.mark.parametrize("stream", [False, True])
def test_user_input_wait_restarts_through_public_chat_and_never_grants_tool_approval(tmp_path, monkeypatch, stream):
    model = ScriptedModel([{"action": "await_user", "content": "请在页面中完成验证"}])
    app, host = app_at(tmp_path, model, monkeypatch)

    def result(response):
        assert response.status_code == 200, response.text
        if not stream:
            return response.json()
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert not any(row.get("type") == "error" for row in events), events
        return next(row for row in events if row.get("type") == "done")

    with TestClient(app) as client:
        token = auth.create_access_token({"sub": "alice"})
        client.headers["Authorization"] = "Bearer " + token
        first = result(client.post("/api/chat", json={"message": "开始测试人工交接", "session_id": "input", "stream": stream}))
        assert first["status"] == "needs_input"
        request = first["input_request"]
        detail = client.get("/api/sessions/input").json()
        assert detail["session_info"]["pending_input"] == request
        assert detail["messages"][-1]["content"] == request["content"]
        assert "model_wire" not in str(detail) and "action_checkpoint" not in str(detail)
    assert len(model.calls) == 1
    resumed_model = ScriptedModel([{"action": "tool_call", "tool_name": "fixture.send", "args": {}}])
    reopened, host2 = app_at(tmp_path, resumed_model, monkeypatch)

    class SensitiveFixture:
        tool_id = name = "fixture.send"
        description = "Inert approval boundary fixture"
        input_schema = {"type": "object", "properties": {}}
        side_effect_level = "external_write"
        calls = 0

        async def invoke(self, args, ctx=None):
            self.calls += 1
            return {"sent": True}

    tool = SensitiveFixture()
    host2.capability_service.register_tool(tool)
    with TestClient(reopened) as client:
        client.headers["Authorization"] = "Bearer " + token
        assert client.get("/api/sessions/input").json()["session_info"]["pending_input"] == request
        second = result(client.post("/api/chat", json={"message": "完成了", "session_id": "input", "stream": stream,
                         "reply_to_input": request["request_id"]}))
        assert second["status"] == "needs_confirmation"
        assert tool.calls == 0
        detail = client.get("/api/sessions/input").json()["session_info"]
        assert detail["pending_input"] is None
        assert detail["pending_confirmation"]["tool_name"] == "fixture.send"
    assert len(resumed_model.calls) == 1


def test_session_pending_confirmation_is_owner_scoped_and_safe(tmp_path, monkeypatch):
    app, host = app_at(tmp_path, ScriptedModel([]), monkeypatch)
    host.message_manager.create_session("approval", user_id="alice")
    host.message_manager.set_pending_confirmation("approval", {"tool_call_id": "call", "tool_name": "example.send", "args": {"text": "hello"},
        "messages": [{"role": "system", "content": "private"}], "model_wire": {"private": True}}, user_id="alice")
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "alice"})
        data = client.get("/api/sessions/approval").json()
        assert data["session_info"]["pending_confirmation"] == {"tool_call_id": "call", "tool_name": "example.send", "arguments": {"text": "hello"}, "status": "needs_confirmation"}
        assert "private" not in str(data)
        client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "bob"})
        denied = client.get("/api/sessions/approval")
        assert denied.status_code >= 400
        assert "example.send" not in denied.text


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("final_failure", [False, True])
def test_calculator_budget_stop_preserves_actual_file_reply_and_reopened_history(tmp_path, monkeypatch, stream, final_failure):
    reply = "The calculator file was created. Canvas mounting and browser validation remain unverified."
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "calculator.html", "content": "<html><button>Calculator</button></html>"}},
        {"status": "error", "code": "MODEL_OUTPUT_LIMIT", "error": "truncated"} if final_failure else reply,
    ])
    app, host = app_at(tmp_path, model, monkeypatch)
    original_settings = host.config_service.get_merged_config

    def limited_settings(user):
        settings = original_settings(user)
        settings["action"].update(max_steps=1, progress_grace_steps=0)
        return settings

    monkeypatch.setattr(host.config_service, "get_merged_config", limited_settings)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "acceptance", "password": "isolated-password"})
        token = login.json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        response = client.post("/api/chat", json={"message": "Create an interactive calculator", "session_id": "calculator", "stream": stream})
        assert response.status_code == 200, response.text
        if stream:
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert not any(event.get("type") == "error" for event in events), events
            result = next(event for event in events if event.get("type") == "done")
            text = result["content"]
        else:
            result = response.json()
            text = result["response"]
        assert text.startswith("Runtime:") if final_failure else text == reply
        assert result["execution_outcome"] == {
            "stop_reason": "budget_exhausted", "goal_status": "unverified",
            "response_source": "runtime" if final_failure else "model",
        }
        saved = client.get("/api/sessions/calculator").json()["messages"]
        assert saved[-1]["content"] == text
        assert saved[-1]["role"] == ("status" if final_failure else "assistant")
        assert saved[-1]["execution_outcome"] == result["execution_outcome"]
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="calculator")
    assert (Path(handle.root_path) / "calculator.html").read_text() == "<html><button>Calculator</button></html>"
    assert len(model.calls) == 2
    assert "workspace.write_file" in (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    reopened_app, _ = app_at(tmp_path, ScriptedModel([]), monkeypatch)
    with TestClient(reopened_app) as client:
        client.headers["Authorization"] = "Bearer " + token
        assert client.get("/api/sessions/calculator").json()["messages"] == saved


@pytest.mark.parametrize("stream", [False, True])
def test_foreground_chat_can_finish_verification_past_step_threshold(tmp_path, monkeypatch, stream):
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "result.txt", "content": "VERIFIED-37"}},
        {"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "result.txt"}},
        finish_from_observation,
    ])
    app, host = app_at(tmp_path, model, monkeypatch)
    settings = host.config_service.get_merged_config("alice")
    settings["action"].update(max_steps=1, progress_grace_steps=2)
    monkeypatch.setattr(host.config_service, "get_merged_config", lambda _: settings)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "alice"})
        response = client.post("/api/chat", json={"message": "Write and verify result.txt", "session_id": "verification", "stream": stream})
        assert response.status_code == 200, response.text
        if stream:
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            result = next(event for event in events if event.get("type") == "done")
            assert "VERIFIED-37" in result["content"]
        else:
            result = response.json()
            assert "VERIFIED-37" in result["response"]
        assert result.get("execution_outcome") is None
    assert len(model.calls) == 3
    assert any("Runtime granted 2 additional decisions" in str(row.get("content")) for row in model.calls[1])
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="verification")
    assert (Path(handle.root_path) / "result.txt").read_text() == "VERIFIED-37"


def test_login_stream_real_artifact_history_and_storage_reconstruction(tmp_path, monkeypatch):
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "answer.txt", "content": "NET=32"}},
        {"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "answer.txt"}}, finish_from_observation,
    ])
    app, host = app_at(tmp_path, model, monkeypatch)
    with TestClient(app) as client:
        assert client.get("/api/sessions").status_code == 401
        assert client.post("/api/auth/login", json={"username": "acceptance", "password": "wrong"}).status_code == 401
        login = client.post("/api/auth/login", json={"username": "acceptance", "password": "isolated-password"})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        streamed = client.post("/api/chat", json={"message": "Write answer.txt then verify its actual content", "session_id": "report", "stream": True})
        assert streamed.status_code == 200
        assert "event: done" in streamed.text and "event: error" not in streamed.text, streamed.text[-2000:]
        handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="report")
        assert (Path(handle.root_path) / "answer.txt").read_text() == "NET=32"
        saved = client.get("/api/sessions/report")
        assert saved.status_code == 200 and "NET=32" in saved.text
    restarted_app, restored = app_at(tmp_path, ScriptedModel([]), monkeypatch)
    with TestClient(restarted_app) as client:
        client.headers["Authorization"] = "Bearer " + token
        assert client.get("/api/sessions/report").json()["messages"] == saved.json()["messages"]
        foreign = auth.create_access_token({"sub": "bob"})
        client.headers["Authorization"] = "Bearer " + foreign
        response = client.get("/api/sessions/report")
        assert response.status_code in {403, 404}, response.text
    assert restored.message_manager.get_messages("report", user_id="alice")


def test_artifact_acceptance_rejects_noop_writer_even_if_agent_reports_success(tmp_path, monkeypatch):
    from agentkit.tools.standard.workspace_tools import WorkspaceWriteFileTool
    from tests.support.evaluation import hard_checks
    from gateway.protocol import RequestType
    import asyncio

    async def broken_writer(self, args, ctx=None):
        return {"ok": True, "path": "answer.txt"}  # deliberate fault injection

    monkeypatch.setattr(WorkspaceWriteFileTool, "invoke", broken_writer)
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "answer.txt", "content": "NET=32"}},
        {"action": "answer", "content": "The report is complete."},
    ])
    host = runtime_at(tmp_path, model)
    response = asyncio.run(host.handle_http_request(method=RequestType.CHAT, params={"message": "Write the report", "session_id": "report"}, user_id="alice"))
    assert response.ok and response.payload["status"] == "success"
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="report")
    assert not (Path(handle.root_path) / "answer.txt").exists()
    failures = hard_checks({"kind": "action", "expect": {"artifacts": {"answer.txt": "NET=32"}}}, {"status": "success", "artifacts": {}})
    assert failures == ["artifact_mismatch:answer.txt"]
