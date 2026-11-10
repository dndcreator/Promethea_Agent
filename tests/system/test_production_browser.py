"""Real React -> Vite proxy -> production launcher -> services/stores; no API fixtures."""
import os
import shutil
import json
from pathlib import Path

import pytest

from tests.support.production import prepare_deployment, production_server, production_ui

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get('CANVAS_TEST_BROWSER_CHANNEL'), reason='opt-in real browser')]


async def test_real_ui_register_login_upload_and_reload(tmp_path):
    from playwright.async_api import async_playwright, expect

    root = tmp_path / 'deployment'
    prepare_deployment(root)
    with production_server(root) as (gateway, launcher_log), production_ui(root, gateway) as base:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel=os.environ['CANVAS_TEST_BROWSER_CHANNEL'], headless=True, chromium_sandbox=True)
            try:
                page = await browser.new_page(viewport={'width': 1440, 'height': 960})
                await page.add_init_script("localStorage.setItem('promethea_ui_lang','zh')")
                errors = []
                responses = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('response', lambda response: responses.append({'url': response.url, 'status': response.status}) if '/api/' in response.url else None)
                await page.goto(base)
                await page.locator('.rail-account').click()
                await page.get_by_role('button', name='还没有账号？注册', exact=True).click()
                dialog = page.get_by_role('dialog', name='注册', exact=True)
                await dialog.get_by_label('用户名', exact=True).fill('browser-acceptance')
                await dialog.get_by_label('密码', exact=True).fill('test-only-password')
                await dialog.get_by_role('button', name='注册', exact=True).click()
                await expect(page.get_by_text('注册成功，请登录。', exact=True)).to_be_visible()
                await page.get_by_role('dialog').get_by_label('密码', exact=True).fill('test-only-password')
                await page.get_by_role('dialog').get_by_role('button', name='登录', exact=True).click()
                await expect(page.locator('.rail-account')).to_have_attribute('title', 'browser-acceptance')
                await page.get_by_role('button', name='文件', exact=True).click()
                await page.get_by_label('选择文件', exact=True).set_input_files({'name': 'verified.txt', 'mimeType': 'text/plain', 'buffer': b'ORCHID-29'})
                await page.get_by_role('button', name='上传并附加', exact=True).click()
                await expect(page.locator('.chat-composer')).to_contain_text('verified.txt')
                await page.get_by_role('button', name='文件', exact=True).click()
                await page.locator('.file-row').filter(has_text='verified.txt').click()
                await expect(page.locator('.file-text-preview')).to_contain_text('ORCHID-29')
                await page.reload()
                await expect(page.locator('.rail-account')).to_have_attribute('title', 'browser-acceptance')
                await page.get_by_role('button', name='文件', exact=True).click()
                await page.locator('.file-row').filter(has_text='verified.txt').click()
                await expect(page.locator('.file-text-preview')).to_contain_text('ORCHID-29')
                output = Path('.tmp/production-qa')
                output.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(output / 'real-file-roundtrip.png'))
                shutil.copyfile(launcher_log, output / 'real-launcher.log')
                assert not errors
            except Exception:
                output = Path('.tmp/production-qa')
                output.mkdir(parents=True, exist_ok=True)
                if browser.contexts and browser.contexts[0].pages:
                    await page.screenshot(path=str(output / 'failure.png'))
                shutil.copyfile(launcher_log, output / 'failed-launcher.log')
                (output / 'failed-responses.json').write_text(json.dumps(responses, indent=2), encoding='utf-8')
                raise
            finally:
                await browser.close()
