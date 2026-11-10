"""React/SDK/SSE/Gateway/Native codec/Runtime/disk, provider packets scripted."""
import json
import os
from pathlib import Path
import threading

import pytest
import uvicorn

from gateway.http.routes import auth
from start_gateway_service import GatewayHTTPServer
from tests.support.http_runtime import app_at
from tests.support.production import free_port, production_ui
from tests.test_model_protocol import core


@pytest.mark.browser
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in Native browser integration")
@pytest.mark.parametrize("width", [1440, 390])
async def test_native_stream_file_delivery_and_reloaded_history(tmp_path, monkeypatch, width):
    from playwright.async_api import async_playwright, expect
    arguments = json.dumps({"tool_name": "workspace.write_file", "args": {"path": "native.txt", "content": "NATIVE-DELIVERY-29"}})
    reply = "Native delivery is saved."
    model, requests = core(monkeypatch, [
        [{"delta": {"tool_calls": [{"index": 0, "id": "native_write", "type": "function", "function": {"name": "tool_call", "arguments": arguments[:30]}}]}, "finish_reason": None},
         {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments[30:]}}]}, "finish_reason": "tool_calls"}],
        [{"delta": {"content": reply}, "finish_reason": "stop"}]], stream=True)
    app, host = app_at(tmp_path, model, monkeypatch)
    host.message_manager.create_session("test-session", user_id="alice")
    server = GatewayHTTPServer(uvicorn.Config(app, host="127.0.0.1", port=free_port(), log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        assert server.startup_complete.wait(15) and server.started
        with production_ui(tmp_path, f"http://127.0.0.1:{server.config.port}") as base:
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
                try:
                    page = await browser.new_page(viewport={"width": width, "height": 960})
                    token = auth.create_access_token({"sub": "alice"})
                    await page.add_init_script(f"localStorage.setItem('auth_token', {token!r}); localStorage.setItem('promethea_ui_lang', 'zh')")
                    await page.goto(base + "/tests/message-content.html?chat")
                    await page.get_by_placeholder("输入消息").fill("Write the requested native.txt file")
                    await page.get_by_title("发送", exact=True).click()
                    await expect(page.get_by_text(reply, exact=True)).to_be_visible(timeout=15000)
                    await page.reload()
                    await expect(page.get_by_text(reply, exact=True)).to_be_visible(timeout=15000)
                    assert len(requests) == 2
                    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="test-session")
                    assert (Path(handle.root_path) / "native.txt").read_text() == "NATIVE-DELIVERY-29"
                    assert next(row for row in requests[-1]["messages"] if row["role"] == "tool")["tool_call_id"] == "native_write"
                    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    output = Path(".tmp/runtime-reliability-qa")
                    output.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(output / f"native-delivery-{width}.png"))
                finally:
                    await browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        assert not thread.is_alive()
