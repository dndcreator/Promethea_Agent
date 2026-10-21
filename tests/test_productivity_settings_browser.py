import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


async def test_personal_accounts_use_existing_secret_settings_and_can_be_removed():
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185").rstrip("/")
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 960})
            _, _, errors = await prepare(page)
            writes = []
            mail = {"imap_configured": False, "smtp_configured": False}

            async def api(route):
                if urlparse(route.request.url).path != "/api/config/secrets":
                    await route.fallback()
                    return
                if route.request.method == "POST":
                    payload = route.request.post_data_json
                    writes.append(payload)
                    if payload.get("remove"):
                        mail.update(imap_configured=False, smtp_configured=False)
                    elif len(writes) == 1:
                        await route.fulfill(status=500, json={"error": "fixture failure"})
                        return
                    else:
                        mail.update(imap_configured=True, smtp_configured=True, imap_host="imap.example.com", smtp_host="smtp.example.com", username="fixture@example.com")
                await route.fulfill(json={"secrets": {"personal_accounts": {"mail": mail, "calendar": {"configured": False}}}})

            await page.route("**/api/**", api)
            await page.goto(base)
            await page.get_by_role("navigation").get_by_role("button", name="设置", exact=True).click()
            await page.get_by_text("个人账号", exact=True).click()
            await page.get_by_label("IMAP 服务器", exact=True).fill("imap.example.com")
            await page.get_by_label("SMTP 服务器", exact=True).fill("smtp.example.com")
            await page.get_by_label("邮箱账号", exact=True).fill("fixture@example.com")
            password = page.get_by_label("邮箱授权码 / 密码", exact=True)
            await password.fill("test-only-password")
            await page.get_by_role("button", name="保存敏感配置", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("保存敏感配置失败")
            await expect(password).to_have_value("test-only-password")
            await page.get_by_role("button", name="保存敏感配置", exact=True).click()
            await expect(password).to_have_value("")
            assert writes[-1]["values"]["MAIL__PASSWORD"] == "test-only-password"
            await expect(page.get_by_role("button", name="移除账号", exact=True)).to_be_visible()
            output = Path(".tmp/frontend-qa")
            output.mkdir(parents=True, exist_ok=True)
            await page.set_viewport_size({"width": 390, "height": 844})
            if await page.locator(".session-sidebar").count():
                await page.get_by_role("button", name="收起会话栏", exact=True).click()
            await page.get_by_label("邮箱账号", exact=True).scroll_into_view_if_needed()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=str(output / "mobile-personal-accounts.png"))
            page.once("dialog", lambda dialog: dialog.accept())
            await page.get_by_role("button", name="移除账号", exact=True).click()
            await expect(page.get_by_text("账号配置已移除", exact=True)).to_be_visible()
            assert writes[-1]["values"] == {} and "MAIL__PASSWORD" in writes[-1]["remove"]
            assert not errors
        finally:
            await browser.close()
