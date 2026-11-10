"""Real account-picker interactions; APIs use synthetic owned identities."""
import json
import asyncio
import os
from pathlib import Path

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


@pytest.mark.parametrize("width", [1440, 390])
async def test_account_switch_failure_cancel_success_and_current_delete(width):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": 900})
            _, _, errors = await prepare(page)
            await page.add_init_script("localStorage.setItem('promethea_known_accounts_v1', JSON.stringify([{user_id:'alice',username:'Alice'},{user_id:'forgotten',username:'ForgetMe'}]))")
            deletes, requests = [], []
            release_delete = asyncio.Event()

            async def auth(route):
                body = route.request.post_data_json
                requests.append(body)
                if body["password"] != "test-password":
                    await route.fulfill(status=401, json={"detail": "Invalid username or password"})
                else:
                    alice = body['username'] == 'Alice'
                    await route.fulfill(json={"access_token": "alice-token" if alice else "shepard-token", "user_id": "alice" if alice else "demo-user", "username": "Alice" if alice else "Shepard"})

            async def profile(route):
                alice = route.request.headers.get("authorization") == "Bearer alice-token"
                await route.fulfill(json={"user_id": "alice" if alice else "demo-user", "username": "Alice" if alice else "Shepard"})

            async def remove(route):
                deletes.append(route.request.headers.get("authorization"))
                if width == 1440:
                    await release_delete.wait()
                await route.fulfill(json={"status": "success"})

            await page.route("**/api/auth/login", auth)
            await page.route("**/api/user/profile", profile)
            await page.route("**/api/config", lambda route: route.fulfill(json={"config": {"api": {}, "memory": {}}}))
            await page.route("**/api/user/delete", remove)
            await page.goto(os.environ["PROMETHEA_UI_TEST_URL"])
            await expect(page.locator('.rail-account')).to_have_attribute('title', 'Shepard')
            await page.get_by_placeholder('输入消息').fill('Shepard private draft')
            await page.locator('.rail-account').click()
            dialog = page.get_by_role('dialog', name='切换账户', exact=True)
            await dialog.get_by_role('button', name='从此浏览器移除 ForgetMe', exact=True).click()
            assert not deletes
            await expect(dialog.get_by_role('button', name='登录 ForgetMe', exact=True)).to_have_count(0)
            await dialog.get_by_role('button', name='登录 Alice', exact=True).click()
            await expect(dialog.get_by_label('用户名', exact=True)).to_have_value('Alice')
            output = Path('.tmp/account-qa'); output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f'picker-{width}.png'))
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await dialog.get_by_label('密码', exact=True).fill('wrong')
            await dialog.get_by_role('button', name='登录', exact=True).click()
            await expect(dialog.get_by_role('alert')).to_be_visible()
            assert await page.evaluate("localStorage.getItem('auth_token')") == 'test-only-token'
            await page.keyboard.press('Escape')
            await expect(dialog).to_have_count(0)
            await expect(page.locator('.rail-account')).to_have_attribute('title', 'Shepard')
            await expect(page.get_by_placeholder('输入消息')).to_have_value('Shepard private draft')
            await page.locator('.rail-account').click()
            dialog = page.get_by_role('dialog', name='切换账户', exact=True)
            await dialog.get_by_role('button', name='登录 Alice', exact=True).click()
            await dialog.get_by_label('密码', exact=True).fill('test-password')
            await dialog.get_by_role('button', name='登录', exact=True).click()
            await expect(page.locator('.rail-account')).to_have_attribute('title', 'Alice')
            await expect(page.get_by_role('dialog')).to_have_count(0)
            await expect(page.get_by_placeholder('输入消息')).to_have_value('')
            stored = await page.evaluate("localStorage.getItem('promethea_known_accounts_v1')")
            assert 'test-password' not in stored and 'alice-token' not in stored
            assert len(requests) == 2
            await page.locator('.rail-account').click()
            await page.get_by_role('button', name='管理当前账户', exact=True).click()
            await expect(page.get_by_role('heading', name='账户', exact=True)).to_be_visible()
            await page.get_by_text('危险区：注销账户', exact=True).click()
            await expect(page.get_by_role('button', name='注销账户', exact=True)).to_be_disabled()
            output = Path('.tmp/account-qa'); output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f'accounts-{width}.png'))
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.get_by_placeholder('Alice', exact=True).fill('Alice')
            await page.get_by_role('button', name='注销账户', exact=True).click()
            if width == 1440:
                await expect(page.get_by_role('button', name='处理中...', exact=True)).to_be_visible()
                await page.locator('.rail-account').click()
                dialog = page.get_by_role('dialog', name='切换账户', exact=True)
                await dialog.get_by_role('button', name='登录 Shepard', exact=True).click()
                await dialog.get_by_label('密码', exact=True).fill('test-password')
                await dialog.get_by_role('button', name='登录', exact=True).click()
                await expect(page.locator('.rail-account')).to_have_attribute('title', 'Shepard')
                release_delete.set()
                await page.wait_for_function("!JSON.parse(localStorage.getItem('promethea_known_accounts_v1')).some(row => row.user_id === 'alice')")
                assert await page.evaluate("localStorage.getItem('auth_token')") == 'shepard-token'
                await expect(page.locator('.rail-account')).to_have_attribute('title', 'Shepard')
            else:
                await expect(page.locator('.rail-account')).to_have_attribute('title', '登录')
            assert deletes == ['Bearer alice-token']
            assert all(account['user_id'] != 'alice' for account in json.loads(await page.evaluate("localStorage.getItem('promethea_known_accounts_v1')")))
            assert not errors
        finally:
            await browser.close()
