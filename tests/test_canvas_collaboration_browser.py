"""Real opaque-frame collaboration in the production shell, with isolated API fixtures."""
import copy
import hashlib
import os
from pathlib import Path

import pytest

from computer.canvas_components import render_component_document
from computer.canvas_document import render_canvas_html
from computer.canvas_semantics import snapshot
from tests.test_canvas_components import document
from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


@pytest.mark.parametrize("width,height", [(1536, 960), (390, 844)])
async def test_component_collaboration_feedback_attention_and_definition_change(width, height):
    from playwright.async_api import async_playwright, expect

    source = render_component_document(document())
    definition = hashlib.sha256(source.encode()).hexdigest()
    state = {"revision": 0, "value": document()["initial_state"]}
    semantics = snapshot(source, state)
    anchor = {"resource": {"kind": "canvas", "id": "calculator", "workspace_id": "default"}, "component_id": "quantity", "definition_revision": definition}
    item = {"expression_id": "quantity_check", "revision": 1, "expected_revision": 0, "kind": "choice", "content": "这里按两个人计算，要先核对人数吗？", "title": "", "tone": "neutral", "state": "open", "hidden": False, "updated_at": "2026-10-25T00:00:00Z", "canvas_anchor": anchor, "choices": [{"id": "later", "label": "稍后再说"}, {"id": "check", "label": "先核对"}]}
    expressions = [item, {**copy.deepcopy(item), "expression_id": "other_app", "content": "This belongs elsewhere", "canvas_anchor": {**anchor, "resource": {**anchor["resource"], "id": "other"}}}]
    surfaces, feedback = [], []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            _, _, errors = await prepare(page)

            async def semantic_api(route):
                if route.request.url.endswith("/context"):
                    surfaces.append(route.request.post_data_json)
                    await route.fulfill(json={"ok": True})
                elif route.request.url.endswith("/feedback"):
                    body = route.request.post_data_json
                    feedback.append(body)
                    assert body["expected_revision"] == item["revision"]
                    item.update(revision=item["revision"] + 1, state="responded" if body["action"] == "respond" else "dismissed", response=body.get("choice_id"))
                    await route.fulfill(json=item)
                else:
                    await route.fulfill(json={"revision": item["revision"], "expressions": expressions})

            async def canvas_state(route):
                if route.request.method == "PUT":
                    body = route.request.post_data_json
                    assert body["expected_revision"] == state["revision"]
                    state.update(revision=state["revision"] + 1, value=body["value"])
                await route.fulfill(json=state)

            await page.route("**/api/semantic-ui**", semantic_api)
            await page.route("**/api/canvas/default/calculator/state", canvas_state)
            await page.route("**/api/canvas/default/calculator/semantics", lambda route: route.fulfill(json=semantics))
            await page.route("**/test-canvas", lambda route: route.fulfill(content_type="text/html", body=render_canvas_html(source)))
            await page.goto(os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185"))
            await page.get_by_role("button", name="画布", exact=True).click()
            frame = page.frame_locator('iframe[title="交互计算器"]')
            card = frame.locator('[data-expression-id="quantity_check"]')
            await expect(card).to_be_visible()
            assert await card.evaluate("node => node.previousElementSibling.contains(document.getElementById('quantity'))")
            await expect(page.locator('.semantic-expressions [data-expression-id="quantity_check"]')).to_have_count(0)
            await expect(frame.get_by_text("This belongs elsewhere", exact=True)).to_have_count(0)
            await frame.get_by_label("Quantity", exact=True).fill("4")
            await page.wait_for_function("document.activeElement?.tagName === 'IFRAME'")
            for _ in range(50):
                if any(row.get("active_component_id") == "quantity" and row.get("focused") for row in surfaces):
                    break
                await page.wait_for_timeout(100)
            assert any(row.get("active_component_id") == "quantity" and row.get("focused") for row in surfaces)
            latest = {row["surface_id"]: row for row in surfaces}
            assert sum(bool(row.get("focused") and row.get("visible")) for row in latest.values()) == 1
            await card.get_by_role("button", name="稍后再说", exact=True).click()
            await expect(card.get_by_role("button", name="稍后再说", exact=True)).to_be_disabled()
            assert feedback == [{"expected_revision": 1, "action": "respond", "choice_id": "later"}]
            await expect(frame.get_by_label("Quantity", exact=True)).to_have_value("4")
            # Same expression id updates in place; no accumulating duplicate interruptions.
            item.update(revision=3, expected_revision=2, kind="note", choices=[], state="open", response=None, content="已保留当前人数，稍后再核对。")
            await expect(card).to_contain_text("已保留当前人数", timeout=6000)
            await expect(frame.locator('.promethea-expression')).to_have_count(1)
            output = Path('.tmp/frontend-qa');output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f'canvas-collaboration-{width}.png'))
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert await frame.locator('body').evaluate("document.documentElement.scrollWidth <= innerWidth")
            # A newer source definition invalidates the old anchor without a reload.
            semantics["definition_revision"] = "b" * 64
            await expect(card).to_have_count(0, timeout=6000)
            assert len(feedback) == 1
            await page.get_by_role("button", name="对话", exact=True).click()
            await page.get_by_placeholder("输入消息").fill("Keep this draft")
            await page.wait_for_timeout(400)
            latest = {row["surface_id"]: row for row in surfaces}
            assert any(row["view"] == "home" and row.get("focused") for row in latest.values())
            assert not any(row["view"] == "canvas" and row.get("visible") for row in latest.values())
            assert not errors
        finally:
            await browser.close()
