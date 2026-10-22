from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.http.routes import ambient
from gateway.http.routes.auth import get_current_user_id
from gateway.task_service import TaskExecutionConflict


def state(session_id="chat", enabled=False):
    return {
        "session_id": session_id,
        "available": True,
        "settings": {"enabled": enabled, "direction": "", "ui_language": "zh", "timezone": "Asia/Shanghai"},
        "revision": 1,
        "status": "idle" if enabled else "disabled",
    }


def client(monkeypatch, service):
    monkeypatch.setattr(ambient, "get_gateway_server", lambda: SimpleNamespace(ambient_service=service))
    app = FastAPI()
    app.include_router(ambient.router)
    app.dependency_overrides[get_current_user_id] = lambda: "alice"
    return TestClient(app)


def test_ambient_routes_are_authenticated_thin_service_adapters(monkeypatch):
    calls = []

    class Service:
        def view(self, user, session):
            calls.append(("view", user, session))
            return state(session)

        def configure(self, user, session, body):
            calls.append(("configure", user, session, body.enabled))
            return state(session, body.enabled)

        def feedback(self, user, session, body):
            calls.append(("feedback", user, session, body.annotation_id, body.decision))
            return state(session, True)

        async def confirm(self, user, session, body):
            calls.append(("confirm", user, session, body.run_id, body.tool_call_id, body.action))
            return state(session, True)

    api = client(monkeypatch, Service())
    assert api.get("/ambient/chat").status_code == 200
    assert api.put("/ambient/chat", json={"enabled": True}).json()["settings"]["enabled"] is True
    assert api.post("/ambient/chat/feedback", json={"annotation_id": "note", "decision": "accepted"}).status_code == 200
    assert api.post("/ambient/chat/confirm", json={"run_id": "run", "tool_call_id": "call", "action": "reject"}).status_code == 200
    assert all(call[1] == "alice" and call[2] == "chat" for call in calls)
    assert api.get("/ambient").status_code == 200
    assert calls[-1] == ("view", "alice", None)


def test_stale_confirmation_is_a_conflict_not_a_server_error(monkeypatch):
    class Service:
        async def confirm(self, *_args):
            raise TaskExecutionConflict("stale approval")

    response = client(monkeypatch, Service()).post(
        "/ambient/chat/confirm",
        json={"run_id": "run", "tool_call_id": "call", "action": "approve"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "stale approval"
