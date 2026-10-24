import os
from pathlib import Path

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


@pytest.mark.parametrize("width,height", [(1440, 960), (390, 844)])
@pytest.mark.parametrize("amount,expected", [(None, "未知"), (0, "$0.000000"), (0.000188, "$0.000188")])
async def test_unknown_zero_and_priced_costs_remain_distinct(width, height, amount, expected):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            _, _, errors = await prepare(page)
            data = {"llm": {"total_calls": 1, "total_tokens": 110, "prompt_tokens": 100, "completion_tokens": 10, "estimated_cost": amount}, "cost": {"estimated_usd": amount, "priced_calls": 0 if amount is None else 1, "unpriced_calls": 1 if amount is None else 0}}
            await page.route("**/api/metrics", lambda route: route.fulfill(json={"metrics": data}))
            await page.goto(os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185"))
            await page.get_by_role("navigation").get_by_role("button", name="系统指标", exact=True).click()
            card = page.get_by_text("估算成本", exact=True).locator("..")
            await expect(card.get_by_text(expected, exact=True)).to_be_visible()
            await expect(card).to_contain_text("已计价: 0/1" if amount is None else "已计价: 1/1")
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            output = Path(".tmp/frontend-qa")
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f"metrics-{width}-{amount}.png"))
            assert not errors, errors
        finally:
            await browser.close()
