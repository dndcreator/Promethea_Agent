"""Guest interaction on the real UI with a synthetic, account-free model API."""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


async def test_guest_conversation_is_temporary_and_private_features_still_require_login():
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185").rstrip("/")
    calls = []
    prompts = []
    errors = []

    async def api(route):
        path = urlparse(route.request.url).path
        calls.append(path)
        if path == "/api/guest":
            data = {"enabled": True, "available": True, "max_messages": 21, "max_input_chars": 16000}
        elif path == "/api/guest/chat":
            assert not route.request.headers.get("authorization")
            prompts.append(route.request.post_data_json)
            data = {"response": f"这是第 {len(prompts)} 次临时回复。", "usage": {"completion_tokens": 12}}
        else:
            data = {}
        await route.fulfill(json=data)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1536, "height": 960})
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.add_init_script("localStorage.clear(); sessionStorage.clear(); localStorage.setItem('promethea_ui_lang','zh')")
            await page.route("**/api/**", api)
            await page.goto(base)
            await expect(page.locator(".guest-chat-status")).to_have_text("临时对话")
            composer = page.get_by_placeholder("输入消息", exact=True)
            await composer.fill("你好，帮我整理一个想法。")
            await composer.press("Enter")
            await expect(page.get_by_text("这是第 1 次临时回复。", exact=True)).to_be_visible()
            await composer.fill("请再简洁一点。")
            await composer.press("Enter")
            await expect(page.get_by_text("这是第 2 次临时回复。", exact=True)).to_be_visible()
            assert prompts[1] == {"messages": [
                {"role": "user", "content": "你好，帮我整理一个想法。"},
                {"role": "assistant", "content": "这是第 1 次临时回复。"},
                {"role": "user", "content": "请再简洁一点。"},
            ]}
            assert not any(path.startswith(("/api/sessions", "/api/memory", "/api/projects", "/api/chat")) for path in calls)
            output = Path(".tmp/frontend-qa")
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / "guest-desktop.png"))
            await page.locator(".new-conversation").click()
            await expect(page.get_by_text("这是第 1 次临时回复。", exact=True)).to_have_count(0)
            await page.get_by_role("navigation").get_by_role("button", name="认知与记忆", exact=True).click()
            await expect(page.get_by_label("用户名", exact=True)).to_be_visible()
            await page.keyboard.press("Escape")
            await expect(page.get_by_label("用户名", exact=True)).to_have_count(0)
            await page.set_viewport_size({"width": 390, "height": 844})
            if await page.locator(".session-sidebar").is_visible():
                await page.get_by_role("button", name="收起会话栏", exact=True).click()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=str(output / "guest-mobile.png"))
            await page.reload()
            await expect(page.get_by_text("这是第 2 次临时回复。", exact=True)).to_have_count(0)
            assert not errors
        finally:
            await browser.close()
