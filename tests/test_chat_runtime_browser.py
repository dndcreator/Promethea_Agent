import json
import os

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


async def test_failed_stream_stays_visible_retry_and_history_are_scoped(tmp_path):
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5177").rstrip("/")
    captured = []

    async def api(route):
        path = route.request.url.split("/api/", 1)[-1].split("?", 1)[0]
        if path == "user/profile":
            data = {"user_id": "test-user", "username": "Test"}
        elif path == "sessions/test-session":
            # Simulate the old server's empty history: it must not erase the live failed turn.
            data = {"messages": [], "session_info": {"title": "交互计算器"}}
        elif path == "sessions/desktop":
            data = {"messages": [], "session_info": {"title": "帮我数桌面图标"}}
        elif path == "chat":
            payload = route.request.post_data_json
            captured.append(payload)
            records = [
                ("session_started", {"session_id": "test-session"}),
                ("reasoning", {"step_id": "step-1", "delta": "先检查画布组件。" + "较长的模型思考。" * 150}),
                ("error", {"error_detail": {"code": "MODEL_OUTPUT_LIMIT", "message": "Output limit"}}),
            ]
            await route.fulfill(content_type="text/event-stream", body="".join(f"event: {kind}\ndata: {json.dumps(payload)}\n\n" for kind, payload in records))
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
            page = await browser.new_page(viewport={"width": 1200, "height": 850})
            await page.add_init_script("localStorage.setItem('auth_token', 'test-only-token'); localStorage.setItem('promethea_ui_lang','zh')")
            await page.route("**/api/**", api)
            await page.goto(base + "/tests/message-content.html?chat")
            await expect(page.get_by_text("此会话没有已保存的消息。", exact=True)).to_be_visible()
            await page.get_by_placeholder("输入消息").fill("请制作交互计算器")
            await page.get_by_title("发送", exact=True).click()
            await expect(page.get_by_text("模型输出额度已用尽，本次未完成。", exact=True)).to_be_visible()
            await expect(page.get_by_text("请制作交互计算器", exact=True)).to_be_visible()
            await expect(page.get_by_text("此会话没有已保存的消息。", exact=True)).to_have_count(0)
            assert captured[0]["metadata"]["ui_language"] == "zh"
            await page.get_by_role("button", name="1 段思考").click()
            step = page.locator("details").filter(has=page.locator("summary", has_text="模型思考 1"))
            assert not await step.evaluate("node => node.open")
            await step.locator("summary").click()
            assert await step.evaluate("node => node.open")
            assert await step.locator("div").evaluate("node => node.clientHeight <= 256")
            await page.get_by_role("button", name="重试", exact=True).click()
            await expect(page.get_by_text("模型输出额度已用尽，本次未完成。", exact=True)).to_have_count(2)
            assert len(captured) == 2
            await page.evaluate("window.selectTestSession('desktop')")
            await expect(page.locator("h1")).to_contain_text("帮我数桌面图标")
            await expect(page.get_by_text("此会话没有已保存的消息。", exact=True)).to_be_visible()
            await expect(page.get_by_text("新的对话", exact=True)).to_have_count(0)
            await page.evaluate("window.setTestLanguage('en')")
            await page.wait_for_function("document.documentElement.lang === 'en'")
            await expect(page.get_by_placeholder("Type a message")).to_be_visible()
            await page.screenshot(path=str(tmp_path / "failed-history.png"))
        finally:
            await browser.close()


async def test_workbench_localized_card_keeps_diagnostics_folded(tmp_path):
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5177").rstrip("/")
    activity = {"activity_id": "tool-1", "event_type": "tool.failed", "kind": "tool", "status": "failed", "subject": "Fetch page", "subject_i18n": {"zh": "读取网页 · example.org", "en": "Fetch page · example.org"}, "summary": "", "detail": {"tool_name": "web.fetch_text", "arguments": {"url": "https://example.org/"}, "error": {"code": "FETCH_FAILED", "message": "Cannot fetch"}}, "references": [{"reference_id": "url-1", "kind": "url", "target": "https://example.org/", "label": "example.org"}]}

    async def api(route):
        if "/api/user/profile" in route.request.url:
            await route.fulfill(json={"user_id": "test-user", "username": "Test"})
        elif "/api/workbench/stream" in route.request.url:
            await route.fulfill(content_type="text/event-stream", body=f'event: snapshot\ndata: {json.dumps({"timeline": [activity], "scope": {"session_id": "test-session"}})}\n\n')
        else:
            await route.fulfill(json={})

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page()
            await page.add_init_script("localStorage.setItem('auth_token','test-only-token')")
            await page.route("**/api/**", api)
            await page.goto(base + "/tests/message-content.html?workbench")
            card = page.get_by_role("button", name="读取网页 · example.org", exact=False)
            await expect(card).to_be_visible()
            await expect(card).to_have_attribute("aria-expanded", "false")
            await expect(page.locator("pre")).to_have_count(0)
            await card.click()
            await expect(page.get_by_text("技术详情", exact=True)).to_be_visible()
            await expect(page.get_by_text("example.org", exact=True)).to_be_visible()
            await expect(page.locator("pre")).not_to_be_visible()
            await page.get_by_text("技术详情", exact=True).click()
            await expect(page.locator("pre")).to_contain_text("FETCH_FAILED")
            await page.evaluate("window.setTestLanguage('en')")
            await expect(page.get_by_role("button", name="Fetch page · example.org", exact=False)).to_be_visible()
            await page.screenshot(path=str(tmp_path / "workbench-disclosure.png"))
        finally:
            await browser.close()


async def test_authoring_settings_use_existing_configuration_and_reject_http_failures():
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5177").rstrip("/")
    updates = []

    async def api(route):
        path = route.request.url.split("/api/", 1)[-1].split("?", 1)[0]
        if path == "config":
            data = {"config": {"agent_name": "Original name", "system_prompt": "Original presentation", "api": {"max_tokens": 2000}, "self_evolve": {"enabled": False, "browser_channel": ""}}}
        elif path == "config/update":
            updates.append(route.request.post_data_json)
            await route.fulfill(status=500 if len(updates) == 1 else 200, json={"status": "error" if len(updates) == 1 else "success"})
            return
        elif path == "user/profile":
            data = {"user_id": "test-user", "username": "Test"}
        elif path == "channels":
            data = []
        else:
            data = {}
        await route.fulfill(json=data)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page()
            dialogs = []

            async def dialog(value):
                dialogs.append(value.message)
                await value.dismiss()

            page.on("dialog", dialog)
            await page.route("**/api/**", api)
            await page.goto(base + "/tests/message-content.html?settings")
            await expect(page.get_by_label("Agent 名称", exact=True)).to_have_value("Original name")
            await expect(page.get_by_label("自定义表现", exact=True)).to_have_value("Original presentation")
            await page.get_by_label("Agent 名称", exact=True).fill("New name")
            await page.get_by_label("自定义表现", exact=True).fill("Concise replies")
            await page.get_by_text("高级能力与可见性", exact=True).click()
            toggle = page.get_by_role("checkbox", name="应用与工具创作", exact=True)
            await expect(toggle).not_to_be_checked()
            await toggle.check()
            await page.get_by_label("画布验证浏览器", exact=True).select_option("msedge")
            await page.get_by_role("button", name="保存更改", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("保存设置失败")
            assert dialogs == []
            await expect(page.get_by_text("设置已保存。", exact=True)).to_have_count(0)
            await page.get_by_role("button", name="保存更改", exact=True).click()
            await expect(page.get_by_text("设置已保存。", exact=True)).to_be_visible()
            config = updates[-1].get("config", updates[-1])
            assert config["self_evolve"] == {"enabled": True, "browser_channel": "msedge"}
            assert config["api"]["max_tokens"] == 2000
            assert config["agent_name"] == "New name"
            assert config["system_prompt"] == "Concise replies"
            assert "user" not in config
        finally:
            await browser.close()
