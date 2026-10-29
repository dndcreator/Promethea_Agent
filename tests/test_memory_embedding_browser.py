import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


@pytest.mark.parametrize("width,height", [(1440, 960), (390, 844)])
async def test_embedding_settings_explicit_download_and_real_status(width, height):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            _, _, errors = await prepare(page)
            commands = []
            state = {"provider": "disabled", "model": "BAAI/bge-small-zh-v1.5", "revision": "7999e1d3359715c523056ef9478215996d62a620",
                     "model_state": "disabled", "index_state": "idle", "supported": True, "indexed": 0, "total": 0}
            async def api(route):
                path = urlparse(route.request.url).path
                if path == "/api/config":
                    await route.fulfill(json={"config": {"memory": {"embedding": {"provider": "disabled", "model": state["model"], "revision": state["revision"]}}}})
                elif path == "/api/config/update":
                    assert route.request.post_data_json["config"]["memory"]["embedding"]["provider"] == "local"
                    state.update(provider="local", model_state="missing_model")
                    await route.fulfill(json={"success": True})
                elif path == "/api/memory/embedding":
                    if route.request.method == "POST":
                        commands.append(route.request.post_data_json)
                        state.update(model_state="downloading")
                    await route.fulfill(json=state)
                else:
                    await route.fallback()
            await page.route("**/api/**", api)
            await page.goto(os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185"))
            await page.get_by_role("navigation").get_by_role("button", name="设置", exact=True).click()
            panel = page.get_by_role("region", name="记忆检索", exact=True)
            await expect(panel).to_be_visible()
            await panel.get_by_label("语义增强", exact=True).select_option("local")
            assert commands == []
            await panel.get_by_role("button", name="下载模型", exact=True).click()
            await expect(panel.get_by_text("正在下载", exact=True)).to_be_visible()
            assert commands == [{"action": "download"}]
            state.update(model_state="ready", index_state="indexing", indexed=12, total=24)
            await panel.get_by_role("button", name="刷新检索状态", exact=True).click()
            await expect(panel.get_by_label("索引进度", exact=True)).to_have_attribute("value", "12")
            await expect(panel.get_by_text("关键词与图关系", exact=True)).to_be_visible()
            await panel.scroll_into_view_if_needed()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert await panel.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
            output = Path(".tmp/frontend-qa")
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f"memory-embedding-{width}.png"))
            assert not errors, errors
        finally:
            await browser.close()
