"""Security mechanism regressions; no real accounts or model calls."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentkit.security.credential_store import ProtectedStore, ProtectedStorageUnavailable, web_origin
from computer.browser import BrowserController
from computer.execution_context import bind_workspace


def test_origin_and_unavailable_storage_fail_closed(tmp_path, monkeypatch):
    assert web_origin("https://EXAMPLE.com:443/a?q=x") == "https://example.com"
    for value in ("http://example.com", "https://user:password@example.com", "file:///tmp/test", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            web_origin(value)
    store = ProtectedStore("alice", tmp_path)
    monkeypatch.setattr(store, "available", lambda: False)
    with pytest.raises(ProtectedStorageUnavailable):
        store.create_credential(url="https://example.com")
    assert not list(tmp_path.rglob("*.sealed"))


@pytest.mark.asyncio
async def test_registered_credential_fill_still_requires_exact_runtime_approval():
    from unittest.mock import AsyncMock
    from agentkit.security.approval import approval_scope
    from gateway.capability_service import CapabilityService, ToolPolicyViolationError
    manifest = Path(__file__).resolve().parents[1] / "agentkit/tools/computer/agent-manifest.json"
    command = json.loads(manifest.read_text())["capabilities"]["invocation_commands"][0]
    invoke = AsyncMock(return_value={"filled": True})
    service = CapabilityService(mcp_manager=SimpleNamespace(get_available_services_filtered=lambda: {"mcp_services": []}))
    service._tool_discovery_initialized = True
    service.register_tool(SimpleNamespace(tool_id="fixture.browser", description="Policy fixture", input_schema=command["inputSchema"],
        side_effect_level=command["sideEffectLevel"], side_effect_selector=command["sideEffectSelector"], invoke=invoke))
    args = {"action": "fill_credential", "selector": "#password", "credential_ref": "cred_" + "a" * 32}
    with pytest.raises(ToolPolicyViolationError):
        await service.call_tool("fixture.browser", args)
    invoke.assert_not_awaited()
    with approval_scope("fixture.browser", args, confirmed=True):
        await service.call_tool("fixture.browser", args)
        with pytest.raises(ToolPolicyViolationError):
            await service.call_tool("fixture.browser", args)
    invoke.assert_awaited_once()


@pytest.mark.skipif(not ProtectedStore.available(), reason="requires actual Windows DPAPI")
def test_real_os_protection_owner_origin_tamper_and_opaque_metadata(tmp_path):
    store = ProtectedStore("alice", tmp_path)
    metadata = store.create_credential(url="https://example.com/signup", username="test-account")
    password = store.password_for_origin(metadata["credential_ref"], "https://example.com/login")
    assert len(password) == 32 and password not in json.dumps(metadata)
    path = store._path(metadata["credential_ref"])
    assert password.encode() not in path.read_bytes()
    assert b"test-account" not in path.read_bytes()
    restored = ProtectedStore("alice", tmp_path)
    assert restored.password_for_origin(metadata["credential_ref"], "https://example.com") == password
    assert password not in json.dumps(restored.list_credentials())
    with pytest.raises(PermissionError):
        restored.password_for_origin(metadata["credential_ref"], "https://other.example.com")
    assert ProtectedStore("bob", tmp_path).read(metadata["credential_ref"]) is None
    with pytest.raises(ValueError):
        store.read("../../escape")
    sealed = bytearray(path.read_bytes())
    sealed[-1] ^= 1
    path.write_bytes(sealed)
    with pytest.raises(PermissionError):
        restored.read(metadata["credential_ref"])


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL") or not ProtectedStore.available(), reason="opt-in real browser and OS protection")
async def test_real_browser_credential_fill_never_exports_password_and_restores_protected_profile(tmp_path, monkeypatch):
    from config import config
    monkeypatch.setattr("config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.system, "browser_headless", True)
    monkeypatch.setattr(config.system, "browser_channel", os.environ["CANVAS_TEST_BROWSER_CHANNEL"])
    controller = BrowserController(workspace_root=str(tmp_path))
    scope = SimpleNamespace(user_id="alice", workspace_id="test", root_path=tmp_path)
    with bind_workspace(scope):
        assert await controller.initialize()
        try:
            await controller.page.route("**/*", lambda route: route.fulfill(body='<label for="pw">Password</label><input id="pw" type="password" autocomplete="new-password">', content_type="text/html"))
            await controller.page.goto("https://example.com/signup")
            created = await controller.execute("create_credential", {"username": "test-account"})
            assert created.success, created.error
            reference = created.result["credential_ref"]
            expected = controller.profile.store.password_for_origin(reference, controller.page.url)
            filled = await controller.execute("fill_credential", {"selector": "#pw", "credential_ref": reference})
            assert filled.success, filled.error
            assert await controller.page.locator("#pw").input_value() == expected
            assert expected not in json.dumps(filled.model_dump())
            assert expected not in str(await controller._snapshot({}))
            assert expected not in await controller._get_content({"type": "html"})
            denied = await controller.execute("evaluate", {"script": "() => document.querySelector('#pw').value"})
            assert not denied.success and expected not in str(denied)
            await controller.context.add_cookies([{"name": "session", "value": "COOKIE-SENTINEL", "url": "https://example.com"}])
        finally:
            await controller.cleanup()
        assert not (tmp_path / "browser_state.json").exists()
        assert all(expected.encode() not in p.read_bytes() and b"COOKIE-SENTINEL" not in p.read_bytes() for p in tmp_path.rglob("*.sealed"))
        restored = BrowserController(workspace_root=str(tmp_path))
        assert await restored.initialize()
        try:
            assert restored._protected_profile
            assert any(c["value"] == "COOKIE-SENTINEL" for c in await restored.context.cookies("https://example.com"))
            assert not (await restored.execute("evaluate", {"script": "() => document.cookie"})).success
            assert restored.profile.store.password_for_origin(reference, "https://example.com") == expected
        finally:
            await restored.cleanup()
