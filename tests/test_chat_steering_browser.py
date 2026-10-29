import os
from pathlib import Path

import pytest


pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


@pytest.mark.parametrize("width", [1280, 390])
async def test_composer_steers_live_stream_and_replaces_rejected_draft(tmp_path, width):
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5186").rstrip("/")
    commands, saved = [], []

    async def api(route):
        path = route.request.url.split("/api/", 1)[-1].split("?", 1)[0]
        if path == "user/profile":
            data = {"user_id": "test-user", "username": "Test"}
        elif path == "sessions/test-session":
            data = {"messages": saved, "session_info": {"title": "流式与引导测试"}}
        elif path == "chat/test-session/steer":
            commands.append(route.request.post_data_json)
            if len(commands) == 1:
                await route.fulfill(status=500, json={"error": "temporary failure"})
            else:
                await route.fulfill(json={"session_id": "test-session", "conversation_turn_id": "t1", "message_id": commands[-1]["message_id"], "status": "queued"})
            return
        elif path == "workbench/stream":
            await route.fulfill(content_type="text/event-stream", body='event: snapshot\ndata: {"timeline":[]}\n\n')
            return
        else:
            data = {}
        await route.fulfill(json=data)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": 850})
            await page.add_init_script("""
                localStorage.setItem('auth_token','test-only-token');
                localStorage.setItem('promethea_ui_lang','zh');
                const originalFetch = window.fetch.bind(window);
                window.chatRequests = 0; window.chatAborts = 0;
                window.fetch = async (input, init = {}) => {
                    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
                    if (url.pathname !== '/api/chat') return originalFetch(input, init);
                    window.chatRequests++;
                    const stream = new ReadableStream({ start(controller) { window.chatController = controller; } });
                    init.signal?.addEventListener('abort', () => {
                        window.chatAborts++;
                        window.chatController.error(new DOMException('Aborted', 'AbortError'));
                    });
                    window.emitChat = (event, payload) => window.chatController.enqueue(new TextEncoder().encode(
                        `event: ${event}\\ndata: ${JSON.stringify(payload)}\\n\\n`));
                    return new Response(stream, {headers: {'Content-Type': 'text/event-stream'}});
                };
            """)
            await page.route("**/api/**", api)
            await page.goto(base + "/tests/message-content.html?chat")
            await expect(page.get_by_text("此会话没有已保存的消息。", exact=True)).to_be_visible()
            composer = page.get_by_placeholder("输入消息")
            await composer.fill("请整理文档")
            await page.get_by_title("发送", exact=True).click()
            await page.wait_for_function("window.chatRequests === 1")
            await page.evaluate("window.emitChat('session_started', {session_id:'test-session',conversation_turn_id:'t1'}); window.emitChat('text', {content:'旧草稿'});")
            await expect(page.get_by_text("旧草稿", exact=True)).to_be_visible()
            await composer.fill("请只保留重点，并使用中文")
            await composer.press("Enter")
            await expect(page.get_by_role("alert")).to_contain_text("引导未确认送达")
            await expect(composer).to_have_value("请只保留重点，并使用中文")
            await page.get_by_role("button", name="引导当前执行", exact=True).click()
            await expect(page.get_by_text("引导已接收", exact=True)).to_be_visible()
            await expect(composer).to_have_value("")
            assert len(commands) == 2 and commands[0] == commands[1]
            assert await page.evaluate("window.chatRequests === 1 && window.chatAborts === 0")
            message_id = commands[-1]["message_id"]
            await page.evaluate("id => { window.emitChat('steering', {status:'applied',message_ids:[id]}); window.emitChat('text', {operation:'replace',content:''}); window.emitChat('text',{content:'最终内容'}); }", message_id)
            await expect(page.get_by_text("引导已应用", exact=True)).to_be_visible()
            await expect(page.get_by_text("最终内容", exact=True)).to_be_visible()
            await expect(page.get_by_text("旧草稿", exact=True)).to_have_count(0)
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            screenshots = Path(__file__).resolve().parents[1] / ".tmp" / "frontend-qa" / "steering"
            screenshots.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshots / f"live-steer-{width}.png"))
            saved.extend([
                {"id": "original", "role": "user", "content": "请整理文档", "conversation_turn_id": "t1"},
                {"id": message_id, "role": "user", "content": "请只保留重点，并使用中文", "conversation_turn_id": "t1", "steering_status": "applied"},
                {"id": "final", "role": "assistant", "content": "最终校验内容", "conversation_turn_id": "t1"},
            ])
            await page.evaluate("window.emitChat('done',{status:'success',session_id:'test-session',content:'最终校验内容'}); window.chatController.close();")
            await expect(page.get_by_text("最终校验内容", exact=True)).to_be_visible()
            await expect(page.get_by_text("请只保留重点，并使用中文", exact=True)).to_have_count(1)
            await expect(page.get_by_title("发送", exact=True)).to_be_visible()
            # Cancellation remains a separate action rather than a side effect of Enter.
            await composer.fill("再整理一次")
            await page.get_by_title("发送", exact=True).click()
            await page.wait_for_function("window.chatRequests === 2")
            await page.get_by_role("button", name="停止当前任务", exact=True).click()
            assert await page.evaluate("window.chatAborts === 1")
        finally:
            await browser.close()
