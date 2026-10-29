from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from gateway.http.routes import memory as routes
from gateway.http.routes.auth import get_current_user_id


@pytest.mark.asyncio
async def test_embedding_routes_are_authenticated_owner_scoped_and_validate_commands(monkeypatch):
    state = {"provider": "local", "model": "fixture/model", "revision": "revision", "model_state": "missing_model",
             "index_state": "idle", "supported": True, "api_key": "never-return"}
    calls = []
    def status(user_id):
        calls.append(("status", user_id))
        return state
    def control(user_id, **kwargs):
        calls.append(("control", user_id, kwargs))
        return state
    service = SimpleNamespace(enabled=True, embedding_status=status, semantic_recall=SimpleNamespace(request_sync=control))
    monkeypatch.setattr(routes, "_get_runtime_components", lambda: service)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/memory/embedding")).status_code == 401
        assert (await client.post("/api/memory/embedding", json={"action": "download"})).status_code == 401
        app.dependency_overrides[get_current_user_id] = lambda: "u1"
        response = await client.get("/api/memory/embedding")
        assert response.status_code == 200 and "api_key" not in response.json()
        response = await client.post("/api/memory/embedding", json={"action": "download", "user_id": "u2"})
        assert response.status_code == 200
        assert calls[-1] == ("control", "u1", {"download": True})
        assert (await client.post("/api/memory/embedding", json={"action": "install_anything"})).status_code == 422
        service.semantic_recall.request_sync = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("missing_dependencies"))
        response = await client.post("/api/memory/embedding", json={"action": "download"})
        assert response.status_code == 409 and response.json()["detail"] == "missing_dependencies"


def test_embedding_credentials_follow_user_env_and_config_never_returns_key(tmp_path, monkeypatch):
    from gateway import user_secrets
    from gateway.http.routes.config import _sanitize_config_for_client
    from gateway.memory_service import MemoryService

    monkeypatch.setattr(user_secrets, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(user_secrets, "USER_SECRETS_DIR", tmp_path / "users")
    user_secrets.update_user_secrets("u1", {"MEMORY__EMBEDDING__API_KEY": "private-key", "MEMORY__EMBEDDING__BASE_URL": "http://localhost:11434/v1"})
    adapter = SimpleNamespace(is_enabled=lambda: False)
    service = MemoryService(memory_adapter=adapter)
    service._get_merged_config = lambda uid: {"memory": {"embedding": {"provider": "openai-compatible", "api_key": ""}}}
    assert service._embedding_settings_for_user("u1")["api_key"] == "private-key"
    assert service._embedding_settings_for_user("u2")["api_key"] == ""
    assert service._embedding_settings_for_user("u1")["base_url"] == "http://localhost:11434/v1"
    payload = _sanitize_config_for_client({"memory": {"embedding": {"api_key": "private-key", "cache_dir": "private-path", "provider": "local"}}})
    assert payload == {"memory": {"embedding": {"provider": "local"}}}
