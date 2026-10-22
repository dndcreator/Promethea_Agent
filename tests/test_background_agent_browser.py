import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


async def test_delegation_card_opens_persistent_child_task_controls():
    from playwright.async_api import async_playwright, expect

    child = {"task_id": "child-task", "title": "后台研究", "status": "running", "revision": 3, "source": "subagent", "session_ids": ["article"], "runs": [{"run_id": "child-turn", "run_type": "subagent", "status": "running"}]}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1536, "height": 960})
            _, _, errors = await prepare(page)
            await page.route("**/api/tasks/child-task", lambda route: route.fulfill(json={"task": child}))

            async def stream(route):
                query = parse_qs(urlparse(route.request.url).query)
                selected = query.get("task_id") == ["child-task"]
                activity = {"activity_id": "delegate", "kind": "tool", "status": "completed", "seq": 1, "subject_i18n": {"zh": "委派子任务 · 后台研究", "en": "Delegate subtask"}, "references": [{"reference_id": "task:child-task", "kind": "task", "target": "child-task", "label": "查看后台研究"}]}
                snapshot = {"scope": {"user_id": "demo-user", "session_id": None if selected else "article", "task_id": "child-task" if selected else None}, "cursor": 1, "timeline": [] if selected else [activity], "task": child if selected else None, "tasks": [child]}
                await route.fulfill(content_type="text/event-stream", body=f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n")

            await page.route("**/api/workbench/stream?*", stream)
            await page.goto(os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185"))
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await page.get_by_role("tab", name="活动", exact=False).click()
            await page.get_by_role("button", name="委派子任务 · 后台研究", exact=False).click()
            await page.get_by_role("button", name="查看后台研究", exact=True).click()
            await expect(page.locator(".observed-task")).to_contain_text("后台研究")
            await expect(page.locator(".runtime-workbench").get_by_role("button", name="停止任务", exact=True)).to_be_visible()
            assert not errors
        finally:
            await browser.close()


async def test_background_parent_reply_refreshes_chat_without_losing_draft():
    from playwright.async_api import async_playwright, expect

    delivered = False
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1536, "height": 960})
            _, _, errors = await prepare(page)

            async def history(route):
                messages = [{"id": "original", "role": "assistant", "content": "后台资料正在整理。"}]
                if delivered:
                    messages.append({"id": "followup", "role": "assistant", "content": "资料已经整理完成，可以继续讨论方案了。", "conversation_turn_id": "delivery-one"})
                await route.fulfill(json={"session_info": {"title": "整理认知架构文章"}, "messages": messages})

            async def stream(route):
                tasks = [{"task_id": "notifications", "source": "agent_inbox", "runs": [{"run_id": "delivery-one", "run_type": "agent_inbox", "status": "completed", "session_id": "article"}]}] if delivered else []
                snapshot = {"scope": {"user_id": "demo-user", "session_id": "article"}, "cursor": 2 if delivered else 1, "timeline": [], "tasks": tasks}
                await route.fulfill(content_type="text/event-stream", body=f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n")

            await page.route("**/api/sessions/article", history)
            await page.route("**/api/workbench/stream?*", stream)
            await page.goto(os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185"))
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await expect(page.get_by_text("后台资料正在整理。", exact=True)).to_be_visible()
            await page.get_by_placeholder("输入消息").fill("这个草稿要保留")
            delivered = True
            await expect(page.get_by_text("资料已经整理完成，可以继续讨论方案了。", exact=True)).to_be_visible(timeout=10000)
            await expect(page.get_by_placeholder("输入消息")).to_have_value("这个草稿要保留")
            output = Path(".tmp/frontend-qa")
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / "agent-ipc-followup.png"))
            assert not errors
        finally:
            await browser.close()
