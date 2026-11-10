"""Material styling must preserve layout, fixed overlays and accessible controls."""
import os
from pathlib import Path

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get('CANVAS_TEST_BROWSER_CHANNEL'), reason='opt-in real browser')]


@pytest.mark.parametrize('width', [1536, 390])
async def test_materials_preserve_chat_overlay_focus_and_reduced_motion(width):
    from playwright.async_api import async_playwright, expect

    output = Path('.tmp/material-qa')
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ['CANVAS_TEST_BROWSER_CHANNEL'], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={'width': width, 'height': 960 if width > 600 else 844}, device_scale_factor=1)
            _, _, errors = await prepare(page)
            await page.goto(os.environ.get('PROMETHEA_UI_TEST_URL', 'http://127.0.0.1:5186'))
            if width < 900:
                await page.get_by_role('button', name='展开会话栏', exact=True).click()
            await page.get_by_role('button', name='整理认知架构文章', exact=True).click()
            composer = page.get_by_placeholder('输入消息', exact=True)
            await composer.fill('我们继续整理这份文章，先核对资料和引用。' * 6)
            await composer.focus()
            assert await composer.evaluate('el => el.scrollWidth <= el.clientWidth')
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(output / f'chat-{width}.png'))
            await page.get_by_label('查看用量', exact=True).click()
            await expect(page.locator('.chat-usage-panel')).to_be_visible()
            box = await page.locator('.chat-usage-panel').bounding_box()
            assert 0 <= box['x'] and box['x'] + box['width'] <= width
            await page.keyboard.press('Escape')
            await expect(page.locator('.chat-usage-panel')).not_to_be_visible()
            if width < 900:
                await page.get_by_role('button', name='展开会话栏', exact=True).click()
            await page.get_by_role('button', name='新建项目', exact=True).click()
            dialog = page.get_by_role('dialog', name='新建项目', exact=True)
            await expect(dialog).to_be_visible()
            await dialog.get_by_label('名称', exact=True).fill('资料整理')
            overlay = page.locator('.feature-overlay')
            bounds = await overlay.bounding_box()
            assert bounds['x'] == 0 and bounds['y'] == 0 and bounds['width'] == width
            assert await dialog.get_by_label('名称', exact=True).evaluate('el => getComputedStyle(el).boxShadow !== "none"')
            await page.screenshot(path=str(output / f'dialog-{width}.png'))
            await page.keyboard.press('Escape')
            await expect(dialog).to_have_count(0)
            await expect(composer).to_have_value('我们继续整理这份文章，先核对资料和引用。' * 6)
            await page.emulate_media(reduced_motion='reduce')
            assert await page.locator('.composer-surface').evaluate('el => getComputedStyle(el).transitionDuration') == '0s'
            await page.emulate_media(forced_colors='active')
            assert await page.locator('.composer-surface').evaluate('el => getComputedStyle(el).borderTopStyle') == 'solid'
            assert not errors
        finally:
            await browser.close()
