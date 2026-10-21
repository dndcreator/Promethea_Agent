import json
import os

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get('CANVAS_TEST_BROWSER_CHANNEL'), reason='opt-in real browser')]


async def test_usage_is_secondary_and_request_tokens_do_not_become_runtime_total():
    from playwright.async_api import async_playwright, expect
    base = os.environ.get('PROMETHEA_UI_TEST_URL', 'http://127.0.0.1:5185').rstrip('/')
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ['CANVAS_TEST_BROWSER_CHANNEL'], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={'width': 1200, 'height': 850})
            await prepare(page)
            await page.route('**/api/metrics', lambda route: route.fulfill(json={'llm': {'total_tokens': 12000}}))

            async def chat(route):
                records = [('session_started', {'session_id': 'article'}), ('text', {'content': '这是一次模型回复。'}), ('done', {'session_id': 'article', 'usage': {'total_tokens': 500}, 'status': 'success'})]
                await route.fulfill(content_type='text/event-stream', body=''.join(f'event: {kind}\ndata: {json.dumps(payload)}\n\n' for kind, payload in records))

            await page.route('**/api/chat', chat)
            await page.goto(base)
            await expect(page.get_by_text('思考强度', exact=True)).to_have_count(0)
            await page.get_by_label('查看用量', exact=True).click()
            await expect(page.get_by_text('本次 Token', exact=True).locator('..')).to_contain_text('-')
            await expect(page.get_by_text('累计 Token', exact=True).locator('..')).to_contain_text('12,000')
            await page.get_by_label('查看用量', exact=True).press('Escape')
            await page.get_by_placeholder('输入消息').fill('你好')
            await page.get_by_title('发送', exact=True).click()
            await expect(page.locator('.chat-heading h1')).to_have_text('整理认知架构文章')
            await page.get_by_label('查看用量', exact=True).click()
            await expect(page.get_by_text('本次 Token', exact=True).locator('..')).to_contain_text('500')
            await expect(page.get_by_text('累计 Token', exact=True).locator('..')).to_contain_text('12,000')
            await expect(page.get_by_text('本次耗时', exact=True).locator('..')).to_contain_text('s')
            await page.get_by_label('查看用量', exact=True).press('Escape')
            await expect(page.get_by_text('本次 Token', exact=True)).not_to_be_visible()
        finally:
            await browser.close()


async def test_project_list_failure_does_not_hide_conversation_history():
    from playwright.async_api import async_playwright, expect
    base = os.environ.get('PROMETHEA_UI_TEST_URL', 'http://127.0.0.1:5185').rstrip('/')
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ['CANVAS_TEST_BROWSER_CHANNEL'], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={'width': 1200, 'height': 850})
            await prepare(page)
            await page.route('**/api/projects', lambda route: route.fulfill(status=503, json={'detail': 'Unavailable'}))
            await page.goto(base)
            await expect(page.get_by_role('alert')).to_contain_text('项目列表加载失败')
            await page.get_by_role('button', name='整理认知架构文章', exact=True).click()
            await expect(page.locator('.chat-heading h1')).to_have_text('整理认知架构文章')
        finally:
            await browser.close()
