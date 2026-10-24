import os
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


@pytest.mark.parametrize("width,height", [(1440, 960), (390, 844)])
@pytest.mark.parametrize("name,label", [("qq", "QQ"), ("feishu", "飞书"), ("dingtalk", "钉钉"), ("wecom", "企业微信")])
async def test_platform_binding_panel_uses_real_controls_without_deployment_secrets(width, height, name, label):
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            _, _, errors = await prepare(page)
            accounts = [{"channel": provider, "account_id": "fixture-app", "running": True, "bound": False} for provider in ("qq", "telegram", "feishu", "dingtalk", "wecom")]
            account = next(row for row in accounts if row["channel"] == name)
            commands = []
            async def api(route):
                path = urlparse(route.request.url).path
                if path == "/api/channels":
                    await route.fulfill(json=accounts)
                elif path == "/api/channels/pairings":
                    commands.append(route.request.post_data_json)
                    await route.fulfill(json={"channel": name, "command": "/bind fixture-proof", "expires_at": time.time() + 600})
                elif path == f"/api/channels/{name}/binding":
                    assert route.request.method == "DELETE"
                    account["bound"] = False
                    await route.fulfill(json={"ok": True})
                else:
                    await route.fallback()
            await page.route("**/api/**", api)
            await page.goto(os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185"))
            await page.get_by_role("navigation").get_by_role("button", name="设置", exact=True).click()
            await page.get_by_text("消息平台", exact=True).click()
            row = page.get_by_text(label, exact=True).locator("..")
            await row.get_by_role("button", name="生成绑定码", exact=True).click()
            await expect(page.get_by_text("/bind fixture-proof", exact=True)).to_be_visible()
            assert commands == [{"channel": name}]
            account["bound"] = True
            await page.get_by_role("button", name="刷新平台状态", exact=True).click()
            await expect(row.get_by_role("button", name="重新绑定", exact=True)).to_be_visible()
            await page.get_by_role("button", name=f"解除绑定 {name}", exact=True).click()
            await expect(row.get_by_role("button", name="生成绑定码", exact=True)).to_be_visible()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            output = Path(".tmp/frontend-qa")
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f"channel-settings-{name}-{width}.png"))
            assert not errors, errors
        finally:
            await browser.close()
