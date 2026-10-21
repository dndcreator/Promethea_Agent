import os
from pathlib import Path

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


async def test_cognition_cloud_is_readable_and_all_feature_pages_fit():
    from playwright.async_api import async_playwright, expect
    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185").rstrip("/")
    output = Path(".tmp/frontend-qa")
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1536, "height": 960}, reduced_motion="reduce")
            _, _, errors = await prepare(page)
            await page.goto(base)
            await page.get_by_role("button", name="认知与记忆", exact=True).click()
            await expect(page.locator(".cognition-thought")).to_have_count(12)
            if await page.locator('.workspace-workbench').count():
                await page.get_by_role("button", name="收起工作台", exact=True).click()
            for width in (1536, 1280, 1024, 390):
                await page.set_viewport_size({"width": width, "height": 960})
                if width < 900 and await page.locator(".session-sidebar").count():
                    await page.get_by_role("button", name="收起会话栏", exact=True).click()
                boxes = await page.locator(".cognition-thought").evaluate_all("nodes => nodes.map(node => { const r=node.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height} })")
                for index, a in enumerate(boxes):
                    assert 0 <= a["x"] < width and a["x"] + a["w"] <= width
                    for b in boxes[index + 1:]:
                        assert not (a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"])
                await page.screenshot(path=str(output / f"cognition-{width}.png"))
            await page.locator(".cognition-thought").first.click()
            await expect(page.get_by_role("button", name="关闭详情", exact=True)).to_be_visible()
            await page.get_by_role("button", name="关闭详情", exact=True).click()
            await page.get_by_role("button", name="列表视图", exact=True).click()
            await expect(page.get_by_placeholder("搜索认知", exact=True)).to_be_visible()
            for index, name in enumerate(("文件", "画布", "工作流", "搜索", "设置", "系统指标", "诊断", "自我进化")):
                await page.get_by_role("navigation", name="主导航", exact=True).get_by_role("button", name=name, exact=True).click()
                await page.wait_for_timeout(100)
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert await page.locator(".workspace-body").evaluate("node => node.scrollWidth <= node.clientWidth")
                await page.screenshot(path=str(output / f"mobile-feature-{index}.png"))
            assert not errors
        finally:
            await browser.close()
