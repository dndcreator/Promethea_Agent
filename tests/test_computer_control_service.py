import asyncio

import pytest
from agentkit.tools.computer.computer_control import ComputerControlService


@pytest.mark.asyncio
async def test_browser_action_alias_goto(monkeypatch):
    svc = ComputerControlService()
    calls = []

    async def fake_execute(capability, action, params=None):
        calls.append((capability, action, params or {}))
        return "SUCCESS"

    monkeypatch.setattr(svc, "execute_action", fake_execute)
    await svc.browser_action(action="goto", url="https://example.com")

    assert calls
    _, action, params = calls[0]
    assert action == "navigate"
    assert params.get("url") == "https://example.com"


@pytest.mark.asyncio
async def test_perception_observe_aggregates_signals(monkeypatch):
    svc = ComputerControlService()

    async def fake_raw(capability, action, params=None):
        if action == "get_url":
            return {"ok": True, "result": "https://example.com"}
        if action == "get_title":
            return {"ok": True, "result": "Example"}
        if action == "get_content":
            return {"ok": True, "result": "Download now"}
        if action == "get_screen_size":
            return {"ok": True, "result": {"width": 1920, "height": 1080}}
        if action == "get_mouse_position":
            return {"ok": True, "result": {"x": 10, "y": 20}}
        if action == "screenshot":
            return {"ok": True, "result": {"size": 1234, "format": "png"}}
        return {"ok": False, "error": "unexpected"}

    monkeypatch.setattr(svc, "_execute_action_raw", fake_raw)
    out = await svc.perception_action(mode="observe", include_screenshot=True)

    assert out.startswith("SUCCESS: perception observe")
    assert "https://example.com" in out
    assert "screenshot_size" in out


@pytest.mark.asyncio
async def test_perception_find_browser_target_passes_arg(monkeypatch):
    svc = ComputerControlService()
    captured = {}

    async def fake_raw(capability, action, params=None):
        if action == "evaluate":
            captured["params"] = params or {}
            return {"ok": True, "result": [{"selector": "button.download", "score": 1.0}]}
        return {"ok": True, "result": None}

    monkeypatch.setattr(svc, "_execute_action_raw", fake_raw)
    out = await svc.perception_action(mode="find_browser_target", target_text="Download", max_candidates=5)

    assert out.startswith("SUCCESS: perception find_browser_target")
    arg = captured["params"].get("arg")
    assert isinstance(arg, dict)
    assert arg.get("needle") == "Download"
    assert arg.get("maxN") == 5


@pytest.mark.asyncio
async def test_perception_find_browser_target_requires_text():
    svc = ComputerControlService()
    out = await svc.perception_action(mode="find_browser_target", target_text="")
    assert out.startswith("ERROR:")

@pytest.mark.asyncio
async def test_browser_snapshot_builds_refs(monkeypatch):
    svc = ComputerControlService()

    async def fake_raw(capability, action, params=None):
        if action == "evaluate":
            return {
                "ok": True,
                "result": [
                    {"selector": "button.download", "text": "Download"},
                    {"selector": "a.more", "text": "More"},
                ],
            }
        return {"ok": False, "error": "unexpected"}

    monkeypatch.setattr(svc, "_execute_action_raw", fake_raw)
    out = await svc.browser_action(action="snapshot", query="Download", max_nodes=5)

    assert out.startswith("SUCCESS: browser snapshot")
    assert svc._browser_snapshot_refs.get("n1") == "button.download"


@pytest.mark.asyncio
async def test_browser_act_uses_ref(monkeypatch):
    svc = ComputerControlService()
    svc._browser_snapshot_refs["n1"] = "button.download"
    calls = []

    async def fake_execute(capability, action, params=None):
        calls.append((capability, action, params or {}))
        return "SUCCESS"

    monkeypatch.setattr(svc, "execute_action", fake_execute)
    out = await svc.browser_action(action="act", ref="n1")

    assert out == "SUCCESS"
    assert calls
    _, action, params = calls[0]
    assert action == "click"
    assert params.get("selector") == "button.download"


@pytest.mark.asyncio
async def test_browser_wait_download_detects_new_file():
    from pathlib import Path
    import shutil

    svc = ComputerControlService()
    download_dir = Path(".pytest-download-wait")
    if download_dir.exists():
        shutil.rmtree(download_dir, ignore_errors=True)

    async def _produce_file():
        await asyncio.sleep(0.05)
        download_dir.mkdir(parents=True, exist_ok=True)
        (download_dir / "demo.zip").write_text("ok", encoding="utf-8")

    task = asyncio.create_task(_produce_file())
    out = await svc.browser_action(
        action="wait_download",
        download_dir=str(download_dir),
        timeout=1000,
        poll_interval_ms=20,
    )
    await task

    assert out.startswith("SUCCESS: download detected")
    assert "demo.zip" in out

    shutil.rmtree(download_dir, ignore_errors=True)

@pytest.mark.asyncio
async def test_browser_workspace_state_and_tab_actions(monkeypatch):
    svc = ComputerControlService()
    calls = []

    async def fake_execute(capability, action, params=None):
        calls.append((capability, action, params or {}))
        return "SUCCESS"

    async def fake_raw(capability, action, params=None):
        if action == "list_tabs":
            return {"ok": True, "result": [{"tab_id": "default", "url": "https://example.com", "title": "Example"}]}
        if action == "get_url":
            return {"ok": True, "result": "https://example.com"}
        if action == "get_title":
            return {"ok": True, "result": "Example"}
        return {"ok": False, "error": "unexpected"}

    monkeypatch.setattr(svc, "execute_action", fake_execute)
    monkeypatch.setattr(svc, "_execute_action_raw", fake_raw)

    out_state = await svc.browser_action(action="workspace_state")
    out_open = await svc.browser_action(action="tab_open", url="https://openai.com")
    out_focus = await svc.browser_action(action="tab_focus", tab_id="tab_1")
    out_close = await svc.browser_action(action="tab_close", tab_id="tab_1")

    assert out_state.startswith("SUCCESS: browser workspace_state")
    assert out_open == "SUCCESS"
    assert out_focus == "SUCCESS"
    assert out_close == "SUCCESS"
    assert any(a == "new_tab" for _, a, _ in calls)
    assert any(a == "switch_tab" for _, a, _ in calls)
    assert any(a == "close_tab" for _, a, _ in calls)

@pytest.mark.asyncio
async def test_perception_ocr_screen_mode(monkeypatch):
    svc = ComputerControlService()

    async def fake_scan(min_confidence=40.0):
        return {
            "ok": True,
            "text": "Download now",
            "items": [{"text": "Download", "x": 100, "y": 200, "conf": 92.0}],
            "image_width": 1920,
            "image_height": 1080,
        }

    monkeypatch.setattr(svc, "_screen_ocr_scan", fake_scan)
    out = await svc.perception_action(mode="ocr_screen")

    assert out.startswith("SUCCESS: perception ocr_screen")
    assert "Download now" in out


@pytest.mark.asyncio
async def test_perception_find_text_on_screen_mode(monkeypatch):
    svc = ComputerControlService()

    async def fake_scan(min_confidence=40.0):
        return {
            "ok": True,
            "text": "Download now",
            "items": [
                {"text": "Download", "x": 100, "y": 200, "conf": 92.0},
                {"text": "Later", "x": 300, "y": 400, "conf": 88.0},
            ],
        }

    monkeypatch.setattr(svc, "_screen_ocr_scan", fake_scan)
    out = await svc.perception_action(mode="find_text_on_screen", target_text="Download", max_candidates=3)

    assert out.startswith("SUCCESS: perception find_text_on_screen")
    assert "matches" in out
    assert "Download" in out

@pytest.mark.asyncio
async def test_perception_click_text_on_screen_mode(monkeypatch):
    svc = ComputerControlService()

    async def fake_scan(min_confidence=40.0):
        return {
            "ok": True,
            "items": [
                {"text": "Download", "x": 120, "y": 260, "conf": 90.0},
            ],
        }

    calls = []
    async def fake_execute(capability, action, params=None):
        calls.append((capability, action, params or {}))
        return "SUCCESS"

    monkeypatch.setattr(svc, "_screen_ocr_scan", fake_scan)
    monkeypatch.setattr(svc, "execute_action", fake_execute)

    out = await svc.perception_action(mode="click_text_on_screen", target_text="Download")
    assert out.startswith("SUCCESS: perception click_text_on_screen")
    assert calls
    cap, action, params = calls[0]
    assert action == "click"
    assert params.get("x") == 120 and params.get("y") == 260

@pytest.mark.asyncio
async def test_perception_execute_target_with_fallback_prefers_dom(monkeypatch):
    svc = ComputerControlService()

    async def fake_browser(needle, max_candidates=8):
        return {"ok": True, "candidates": [{"selector": "button.download", "text": "Download"}]}

    async def fake_screen(needle, max_candidates=8):
        return {"ok": True, "candidates": [{"text": "Download", "x": 10, "y": 20}]}

    calls = []
    async def fake_execute(capability, action, params=None):
        calls.append((capability, action, params or {}))
        return "SUCCESS"

    monkeypatch.setattr(svc, "_find_browser_candidates", fake_browser)
    monkeypatch.setattr(svc, "_find_screen_text_candidates", fake_screen)
    monkeypatch.setattr(svc, "execute_action", fake_execute)

    out = await svc.perception_action(mode="execute_target_with_fallback", target_text="Download")
    assert out.startswith("SUCCESS: perception execute_target_with_fallback")
    assert "'path': 'dom'" in out


@pytest.mark.asyncio
async def test_perception_execute_target_with_fallback_uses_ocr(monkeypatch):
    svc = ComputerControlService()

    async def fake_browser(needle, max_candidates=8):
        return {"ok": True, "candidates": []}

    async def fake_click(mode="", target_text="", max_candidates=8, **kwargs):
        if mode == "click_text_on_screen":
            return "SUCCESS: perception click_text_on_screen\nResult: {'target': 'Download'}"
        return "ERROR"

    monkeypatch.setattr(svc, "_find_browser_candidates", fake_browser)
    monkeypatch.setattr(svc, "perception_action", fake_click)

    out = await ComputerControlService.perception_action(svc, mode="execute_target_with_fallback", target_text="Download")
    assert out.startswith("SUCCESS: perception execute_target_with_fallback")
    assert "'path': 'ocr'" in out

@pytest.mark.asyncio
async def test_content_action_delegates_web_fetch(monkeypatch):
    svc = ComputerControlService()

    class Dummy:
        async def web_fetch(self, **kwargs):
            return {"ok": True, "kind": "web_fetch", "kwargs": kwargs}

    monkeypatch.setattr(svc, "_get_content_tools", lambda: Dummy())
    out = await svc.content_action(action="web_fetch", url="https://example.com")
    assert out["ok"] is True
    assert out["kind"] == "web_fetch"


@pytest.mark.asyncio
async def test_runtime_action_delegates_sessions_list(monkeypatch):
    svc = ComputerControlService()

    class Dummy:
        async def sessions_action(self, **kwargs):
            return {"ok": True, "kind": "sessions", "kwargs": kwargs}

    monkeypatch.setattr(svc, "_get_runtime_tools", lambda: Dummy())
    out = await svc.runtime_action(action="sessions_list", user_id="u1")
    assert out["ok"] is True
    assert out["kind"] == "sessions"


@pytest.mark.asyncio
async def test_schedule_action_delegates_create_job(monkeypatch):
    svc = ComputerControlService()

    class Dummy:
        async def create_job(self, **kwargs):
            return {"ok": True, "kind": "create_job", "kwargs": kwargs}

    monkeypatch.setattr(svc, "_get_cron_tools", lambda: Dummy())
    out = await svc.schedule_action(
        action="create_job",
        name="h",
        interval_seconds=60,
        service_name="runtime_tools",
        tool_name="gateway_action",
    )
    assert out["ok"] is True
    assert out["kind"] == "create_job"


@pytest.mark.asyncio
async def test_graph_action_delegates_upsert(monkeypatch):
    svc = ComputerControlService()

    class Dummy:
        async def upsert_node(self, **kwargs):
            return {"ok": True, "kind": "upsert", "kwargs": kwargs}

    monkeypatch.setattr(svc, "_get_node_tools", lambda: Dummy())
    out = await svc.graph_action(action="upsert_node", node_id="n1", kind="task")
    assert out["ok"] is True
    assert out["kind"] == "upsert"

@pytest.mark.asyncio
async def test_process_action_blocked_by_sandbox():
    svc = ComputerControlService()

    class _Policy:
        def check_command(self, command, cwd=".", workspace_root=None):
            class _D:
                allowed = False
                reason = "blocked"
            return _D()

    svc._sandbox = _Policy()
    out = await svc.process_action(action="run", command="python -V")
    assert out.startswith("ERROR: sandbox blocked command")


@pytest.mark.asyncio
async def test_fs_action_blocked_by_sandbox():
    svc = ComputerControlService()

    class _Policy:
        def check_path(self, path, intent="read", workspace_root=None):
            class _D:
                allowed = False
                reason = "blocked"
            return _D()

    svc._sandbox = _Policy()
    out = await svc.fs_action(action="write", path="a.txt", content="x")
    assert out.startswith("ERROR: sandbox blocked path")


@pytest.mark.asyncio
async def test_content_action_web_fetch_blocked_by_sandbox():
    svc = ComputerControlService()

    class _Policy:
        def check_url(self, url):
            class _D:
                allowed = False
                reason = "blocked"
            return _D()

    svc._sandbox = _Policy()
    out = await svc.content_action(action="web_fetch", url="https://example.com")
    assert out.get("ok") is False
    assert "sandbox blocked web_fetch" in out.get("error", "")
