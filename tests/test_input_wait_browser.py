"""UI contract regression with synthetic public API, not a live Agent task."""
import json
import os
from pathlib import Path

import pytest

from tests.test_frontend_workspace_browser import prepare


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in UI browser")
@pytest.mark.parametrize("width", [1440, 390])
async def test_wait_restores_and_reply_is_bound_to_the_current_request(width):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": 900})
            _, _, errors = await prepare(page)
            request = {"request_id": "input-current", "content": "请完成页面验证", "input_kind": "acknowledgement"}
            posted = []

            async def session(route):
                await route.fulfill(json={"session_info": {"title": "人工交接", "pending_input": request}, "messages": [
                    {"role": "user", "content": "继续工作", "id": "user"},
                    {"role": "assistant", "content": request["content"], "id": "assistant"}]})

            async def chat(route):
                posted.append(route.request.post_data_json)
                await route.fulfill(content_type="text/event-stream", body='event: done\ndata: ' + json.dumps({
                    "type": "done", "session_id": "article", "status": "needs_input", "content": request["content"], "input_request": request}) + '\n\n')

            await page.route("**/api/sessions/article", session)
            await page.route("**/api/chat", chat)
            await page.goto(os.environ["PROMETHEA_UI_TEST_URL"])
            if width < 600:
                await page.get_by_role("button", name="展开会话栏", exact=True).click()
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await expect(page.locator(".chat-heading")).to_contain_text("等待你回复")
            await page.get_by_placeholder("输入消息", exact=True).fill("完成了")
            async with page.expect_response(lambda response: response.url.endswith("/api/chat")):
                await page.get_by_title("发送", exact=True).click()
            await expect(page.locator(".chat-heading")).to_contain_text("等待你回复")
            assert posted and posted[0]["reply_to_input"] == request["request_id"]
            assert posted[0]["message"] == "完成了"
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            output = Path(".tmp/input-wait-ui")
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f"wait-{width}.png"))
            assert not errors, errors
        finally:
            await browser.close()
