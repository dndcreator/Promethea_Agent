"""Real React/SDK/SSE/services/disk/history; only model I/O is scripted."""
import os
from pathlib import Path
import threading

import pytest
import uvicorn

from gateway.http.routes import auth
from start_gateway_service import GatewayHTTPServer
from tests.support.http_runtime import app_at
from tests.support.production import free_port, production_ui
from tests.support.runtime import ScriptedModel

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


@pytest.mark.parametrize("fallback,width", [(False, 1440), (True, 390)])
async def test_real_chat_retains_partial_progress_after_reload(tmp_path, monkeypatch, fallback, width):
    from playwright.async_api import async_playwright, expect

    reply = "File created. Canvas mounting and interaction are not verified."
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "calculator.html", "content": "<button>Calculator</button>"}},
        ConnectionError("simulated provider disconnect") if fallback else reply,
    ])
    app, host = app_at(tmp_path, model, monkeypatch)
    host.message_manager.create_session("test-session", user_id="alice")
    settings = host.config_service.get_merged_config("alice")
    settings["action"].update(max_steps=1, progress_grace_steps=0)
    monkeypatch.setattr(host.config_service, "get_merged_config", lambda _: settings)
    port = free_port()
    server = GatewayHTTPServer(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        assert server.startup_complete.wait(15) and server.started
        with production_ui(tmp_path, f"http://127.0.0.1:{port}") as base:
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
                try:
                    page = await browser.new_page(viewport={"width": width, "height": 960})
                    token = auth.create_access_token({"sub": "alice"})
                    await page.add_init_script(f"localStorage.setItem('auth_token', {token!r}); localStorage.setItem('promethea_ui_lang', 'zh')")
                    await page.goto(base + "/tests/message-content.html?chat")
                    await page.get_by_placeholder("输入消息").fill("请创建交互计算器")
                    await page.get_by_title("发送", exact=True).click()
                    if fallback:
                        await expect(page.get_by_text("运行状态", exact=True)).to_be_visible()
                        await expect(page.get_by_text("目标完成情况尚未验证；已提交的结果和产物已保留。", exact=False)).to_be_visible()
                    else:
                        await expect(page.get_by_text(reply, exact=True)).to_be_visible()
                        await expect(page.get_by_text("已保留进度 · 目标未验证", exact=True)).to_be_visible()
                    await expect(page.get_by_text("本次请求未完成。", exact=True)).to_have_count(0)
                    await page.reload()
                    await expect(page.get_by_placeholder("输入消息")).to_be_visible()
                    await expect(page.get_by_text("运行状态" if fallback else reply, exact=True)).to_be_visible()
                    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert len(model.calls) == 2
                    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="test-session")
                    assert (Path(handle.root_path) / "calculator.html").read_text() == "<button>Calculator</button>"
                    output = Path(".tmp/runtime-reliability-qa")
                    output.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(output / ("runtime-notice-mobile.png" if fallback else "partial-progress-desktop.png")))
                finally:
                    await browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        assert not thread.is_alive()
