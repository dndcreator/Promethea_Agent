import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


@pytest.mark.parametrize("width,height", [(1536, 960), (390, 844)])
async def test_semantic_expressions_are_scoped_interactive_and_do_not_replace_chat(width, height):
    from playwright.async_api import async_playwright, expect

    def expression(identity, kind, content, **values):
        return {"expression_id": identity, "expected_revision": 0, "revision": 1, "kind": kind, "content": content, "title": "", "tone": "neutral", "state": "open", "hidden": False, "updated_at": "2026-10-23T00:00:00Z", "choices": [], **values}

    state = {"revision": 1, "expressions": [
        expression("warm", "gesture", "我帮你留意着，不急。", tone="warm"),
        expression("decision", "choice", "先看哪一部分？", session_id="article", choices=[{"id": "cost", "label": "先看成本"}, {"id": "method", "label": "先看方法"}]),
        expression("source", "note", "这里的结论还需要核对。", session_id="article", message_id="article-assistant"),
        expression("elsewhere", "panel", "另一个对话的关注点", session_id="desktop"),
    ]}
    commands, surfaces = [], []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            _, _, errors = await prepare(page)

            async def stream(route):
                query = parse_qs(urlparse(route.request.url).query)
                snapshot = {"scope": {"user_id": "demo-user", "session_id": (query.get("session_id") or [None])[0]}, "cursor": state["revision"], "timeline": [], "tasks": [], "semantic_ui": state}
                await route.fulfill(content_type="text/event-stream", body=f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n")

            async def feedback(route):
                body = route.request.post_data_json
                commands.append(body)
                identity = urlparse(route.request.url).path.split("/")[-2]
                item = next(row for row in state["expressions"] if row["expression_id"] == identity)
                assert body["expected_revision"] == item["revision"]
                item.update(revision=item["revision"] + 1, state="responded" if body["action"] == "respond" else "dismissed", response=body.get("choice_id"))
                state["revision"] += 1
                await route.fulfill(json=item)

            async def context(route):
                surfaces.append(route.request.post_data_json)
                await route.fulfill(json={"ok": True})

            await page.route("**/api/workbench/stream?*", stream)
            await page.route("**/api/semantic-ui/*/feedback", feedback)
            await page.route("**/api/semantic-ui/context", context)
            await page.goto(os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185"))
            if width < 600:
                await page.get_by_role("button", name="展开会话栏", exact=True).click()
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await expect(page.get_by_text("我帮你留意着，不急。", exact=True)).to_be_visible()
            await expect(page.get_by_text("这里的结论还需要核对。", exact=True)).to_be_visible()
            await expect(page.get_by_text("另一个对话的关注点", exact=True)).to_have_count(0)
            await page.get_by_placeholder("输入消息").fill("这段草稿保留下来")
            await page.get_by_role("button", name="先看成本", exact=True).click()
            await expect(page.get_by_role("button", name="先看成本", exact=True)).to_be_disabled()
            assert commands == [{"expected_revision": 1, "action": "respond", "choice_id": "cost"}]
            await page.locator('[data-expression-id="warm"]').get_by_role("button", name="收起", exact=True).click()
            await expect(page.get_by_text("我帮你留意着，不急。", exact=True)).to_have_count(0)
            await expect(page.get_by_placeholder("输入消息")).to_have_value("这段草稿保留下来")
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            output = Path(".tmp/frontend-qa")
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f"semantic-ui-{width}.png"))
            await page.reload()
            if width < 600:
                await page.get_by_role("button", name="展开会话栏", exact=True).click()
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await expect(page.get_by_role("button", name="先看成本", exact=True)).to_be_disabled()
            assert len(commands) == 2
            assert any(row.get("view") == "chat" and {"kind": "session", "id": "article"} in row.get("objects", []) for row in surfaces)
            assert not errors
        finally:
            await browser.close()
