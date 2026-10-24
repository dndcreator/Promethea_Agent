import asyncio
import os

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


async def test_profile_reply_cannot_restore_logged_out_or_replaced_identity():
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5177").rstrip("/")
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page()
            await page.add_init_script("sessionStorage.setItem('auth_token','old-token')")
            pending = asyncio.Queue()

            async def api(route):
                if "/api/user/profile" in route.request.url:
                    await pending.put(route)
                else:
                    await route.fulfill(json={})

            await page.route("**/api/**", api)
            await page.goto(base + "/tests/message-content.html?auth")
            initial = await asyncio.wait_for(pending.get(), 10)
            await page.wait_for_function("Boolean(window.testAuth)")
            await page.evaluate("testAuth.login('new-token', {user_id:'new-user', username:'New'})")
            await initial.fulfill(json={"user_id": "old-user", "username": "Old"})
            await expect(page.locator("#profile")).to_have_text("new-user")
            await page.evaluate("void testAuth.verifySession()")
            stale = await asyncio.wait_for(pending.get(), 10)
            await page.evaluate("testAuth.logout()")
            await stale.fulfill(json={"user_id": "new-user", "username": "New"})
            await expect(page.locator("#profile")).to_have_text("guest")
            assert await page.evaluate("sessionStorage.getItem('auth_token')") is None
        finally:
            await browser.close()


async def test_sensitive_configuration_http_failure_keeps_draft_and_shows_failure():
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5177").rstrip("/")
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page()
            notices = []

            async def dialog(value):
                notices.append(value.message)
                await value.dismiss()

            page.on("dialog", dialog)

            async def api(route):
                if route.request.method == "POST" and "/api/config/secrets" in route.request.url:
                    await route.fulfill(status=500, json={"error": "save failed"})
                elif "/api/channels" in route.request.url:
                    await route.fulfill(json=[])
                else:
                    await route.fulfill(json={"config": {}, "secrets": {}})

            await page.route("**/api/**", api)
            await page.goto(base + "/tests/message-content.html?settings")
            draft = page.get_by_label("API Key", exact=True)
            await draft.fill("test-only-unsaved-key")
            await page.get_by_role("button", name="保存敏感配置", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("保存敏感配置失败")
            await expect(page.get_by_text("敏感配置已保存。", exact=True)).to_have_count(0)
            await expect(draft).to_have_value("test-only-unsaved-key")
            assert notices == []
        finally:
            await browser.close()
