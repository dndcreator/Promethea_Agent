"""Real HTTP routes, JWT login, Gateway and disk effects with scripted model I/O.

This is in-process system acceptance, not full launcher/browser/provider E2E.
"""
from pathlib import Path

from fastapi.testclient import TestClient
from gateway.http.routes import auth
from tests.support.runtime import ScriptedModel, finish_from_observation, runtime_at
from tests.support.http_runtime import app_at


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
