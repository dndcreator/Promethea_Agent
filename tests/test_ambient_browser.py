import json
import os
from urllib.parse import parse_qs, urlparse
from pathlib import Path

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


async def test_ambient_controls_inline_feedback_and_draft_survive_background_updates():
    from playwright.async_api import async_playwright, expect

    state = {"session_id": "article", "available": True, "settings": {"enabled": False, "direction": "", "ui_language": "zh"}, "revision": 0, "status": "disabled", "attention": [], "questions": [], "reflection": ""}
    note = {"id": "note", "message_id": "answer", "selected_text": "周五", "start_offset": 5, "end_offset": 7, "query": "交付时间", "response": "需要核对时区。", "source": "agent", "state": "open"}
    commands = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1536, "height": 960})
            _, _, errors = await prepare(page)

            async def ambient(route):
                if route.request.method == "PUT":
                    state["settings"] = route.request.post_data_json
                    state["revision"] += 1
                    state["status"] = "idle" if state["settings"]["enabled"] else "disabled"
                elif route.request.method == "POST":
                    commands.append(route.request.post_data_json)
                    note["state"] = commands[-1]["decision"]
                    state["revision"] += 1
                await route.fulfill(json=state)

            async def history(route):
                await route.fulfill(json={"session_info": {"title": "整理认知架构文章", "followups": [note] if state["revision"] > 1 else []}, "messages": [{"id": "answer", "role": "assistant", "content": "交付日期是周五。"}]})

            async def stream(route):
                snapshot = {"scope": {"user_id": "demo-user", "session_id": "article"}, "cursor": 1, "timeline": [], "tasks": [], "ambient": state}
                await route.fulfill(content_type="text/event-stream", body=f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n")

            await page.route("**/api/ambient", ambient)
            await page.route("**/api/ambient/**", ambient)
            await page.route("**/api/sessions/article", history)
            await page.route("**/api/workbench/stream?*", stream)
            await page.goto(os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185"))
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await page.get_by_role("tab", name="工作", exact=True).click()
            await expect(page.get_by_role("switch", name="主动协作")).not_to_be_checked()
            await page.get_by_role("switch", name="主动协作").check()
            await page.get_by_label("关注方向", exact=True).fill("帮我留意文章的交付约束")
            await page.get_by_role("button", name="保存关注方向", exact=True).click()
            await page.get_by_placeholder("输入消息").fill("我正在阅读，草稿不要丢")
            await expect(page.get_by_text("交付时间", exact=True)).to_be_visible(timeout=10000)
            await page.get_by_role("button", name="周五", exact=True).click()
            await expect(page.get_by_text("需要核对时区。", exact=True)).to_be_visible()
            await page.get_by_role("button", name="采纳", exact=True).click()
            await expect(page.get_by_text("已采纳", exact=True)).to_be_visible()
            assert commands[-1] == {"annotation_id": "note", "decision": "accepted", "comment": ""}
            await expect(page.get_by_placeholder("输入消息")).to_have_value("我正在阅读，草稿不要丢")
            await page.get_by_role("button", name="统计桌面图标", exact=True).click()
            await expect(page.get_by_role("switch", name="主动协作")).to_be_checked()
            await expect(page.get_by_label("关注方向", exact=True)).to_have_value("帮我留意文章的交付约束")
            await page.locator(".new-conversation").click()
            await expect(page.get_by_role("switch", name="主动协作")).to_be_checked()
            await expect(page.get_by_label("关注方向", exact=True)).to_have_value("帮我留意文章的交付约束")
            for viewport in ({"width": 1536, "height": 960}, {"width": 390, "height": 844}):
                await page.set_viewport_size(viewport)
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                output = Path(".tmp/frontend-qa")
                output.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(output / f"ambient-{viewport['width']}.png"))
            assert not errors
        finally:
            await browser.close()


async def test_welcome_only_generates_for_visible_empty_visits_and_selected_language():
    from playwright.async_api import async_playwright, expect

    requests = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1536, "height": 960})
            _, _, errors = await prepare(page)

            async def welcome(route):
                query = parse_qs(urlparse(route.request.url).query)
                requests.append(query)
                greeting = "Welcome in English" if query.get("lang") == ["en"] else "中文问候"
                await route.fulfill(json={"greeting": greeting, "context_hint": "", "suggested_actions": ["Continue"]})

            await page.route("**/api/welcome?*", welcome)
            await page.goto(os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185"))
            await expect(page.get_by_text("中文问候", exact=True)).to_be_visible()
            assert len(requests) == 1 and requests[0].get("visit_id")
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await page.get_by_role("button", name="切换语言", exact=True).click()
            await page.get_by_role("button", name="Tasks", exact=True).click()
            await page.get_by_role("button", name="Chat", exact=True).click()
            assert len(requests) == 1
            await page.get_by_role("button", name="New chat", exact=True).click()
            await expect(page.get_by_text("Welcome in English", exact=True)).to_be_visible()
            assert len(requests) == 2
            assert requests[0]["visit_id"] != requests[1]["visit_id"]
            assert not errors
        finally:
            await browser.close()
