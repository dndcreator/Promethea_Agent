"""The real composer sends the optional mode through the existing SDK stream."""
import os
from pathlib import Path

import pytest

from tests.test_frontend_workspace_browser import prepare


pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


async def test_home_multi_agent_switch_and_request_metadata():
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185")
    requests = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1536, "height": 960})
            _, _, errors = await prepare(page)
            await page.route("**/api/config", lambda route: route.fulfill(json={"config": {"multi_agent": {"enabled": True}}}))

            async def chat(route):
                requests.append(route.request.post_data_json)
                await route.fulfill(content_type="text/event-stream", body='event: text\ndata: {"content":"已收到请求"}\n\nevent: done\ndata: {"status":"success"}\n\n')

            await page.route("**/api/chat", chat)
            await page.goto(base)
            switch = page.get_by_role("switch", name="多 Agent", exact=True)
            await expect(switch).to_be_visible()
            await expect(switch).not_to_be_checked()
            await switch.check()
            output = Path(".tmp/frontend-qa")
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / "multi-agent-desktop.png"))
            composer = page.get_by_placeholder("输入消息", exact=True)
            await composer.fill("并行研究两个独立问题")
            await composer.press("Enter")
            await expect(switch).to_be_enabled()
            assert requests[0]["metadata"]["multi_agent"] is True
            await switch.uncheck()
            await composer.fill("这次直接回答")
            await composer.press("Enter")
            await expect(switch).to_be_enabled()
            assert requests[1]["metadata"]["multi_agent"] is False
            await page.set_viewport_size({"width": 390, "height": 844})
            if await page.get_by_role("button", name="收起工作台", exact=True).is_visible():
                await page.get_by_role("button", name="收起工作台", exact=True).click()
            if await page.get_by_role("button", name="收起会话栏", exact=True).is_visible():
                await page.get_by_role("button", name="收起会话栏", exact=True).click()
            await expect(switch).to_be_visible()
            await switch.check()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=str(output / "multi-agent-mobile.png"))
            assert not errors
        finally:
            await browser.close()
