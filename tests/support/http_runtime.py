"""Compose production HTTP routes over an isolated test Runtime and identity store."""
from datetime import datetime, timezone

from fastapi import FastAPI

from gateway.http import dispatcher
from gateway.http.identity_store import IdentityStore
from gateway.http.user_manager import UserManager
from gateway.http.routes import auth, chat, sessions
from gateway import user_secrets
from tests.support.runtime import runtime_at


def app_at(root, model, overrides):
    host = runtime_at(root, model)
    identities = IdentityStore(root / "identities.sqlite3")
    if identities.get_by_id("alice") is None:
        identities.create({"user_id": "alice", "username": "acceptance", "password_hash": UserManager._hash_password("isolated-password"),
                           "agent_name": "Promethea", "created_at": datetime.now(timezone.utc).isoformat()})
    manager = UserManager.__new__(UserManager)
    manager.users_dir, manager.identity_store = root / "users", identities
    manager.connector, manager._legacy_neo4j_pending = None, False
    overrides.setattr(auth, "user_manager", manager)
    overrides.setattr(auth, "SECRET_KEY", "isolated-test-signing-key-not-a-deployment-secret")
    overrides.setattr(user_secrets, "USER_SECRETS_DIR", root / "users")
    overrides.setattr(user_secrets, "ENV_FILE", root / "missing.env")
    overrides.setattr(dispatcher, "get_gateway_server", lambda: host)
    overrides.setattr(chat, "get_gateway_server", lambda: host)
    overrides.setattr(sessions, "get_gateway_server", lambda: host)
    app = FastAPI()
    for router in (auth.router, chat.router, sessions.router):
        app.include_router(router, prefix="/api")
    return app, host
