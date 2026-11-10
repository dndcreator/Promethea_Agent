import json
import os
from pathlib import Path

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
                ("reasoning", {"step_id": "step-1", "delta": "先检查画布组件。" + "较长的模型思考。" * 150 + "推理末尾标记"}),
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
            await page.get_by_role("button", name="工作过程", exact=True).click()
            await expect(page.get_by_text("先检查画布组件。", exact=False)).to_have_count(0)
            await page.get_by_role("button", name="推理过程", exact=True).click()
            step = page.get_by_role("button", name="模型推理 1", exact=True)
            await expect(step).to_have_attribute("aria-expanded", "false")
            await expect(page.get_by_text("先检查画布组件。", exact=False)).to_have_count(0)
            await step.click()
            await expect(page.get_by_text("先检查画布组件。", exact=False)).to_be_visible()
            await expect(page.get_by_text("推理末尾标记", exact=False)).to_have_count(0)
            await page.get_by_role("button", name="下一段", exact=True).click()
            await expect(page.get_by_text("先检查画布组件。", exact=False)).to_have_count(0)
            await step.click()
            await expect(page.get_by_role("button", name="下一段", exact=True)).to_have_count(0)
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


@pytest.mark.parametrize("width", [1440, 390])
async def test_process_layers_language_and_prose_only_history(tmp_path, width):
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5177").rstrip("/")
    tree_reads = []
    thought = "先核对报价的数量。" + "验证单价与数量是否一致。" * 150 + "完整推理末尾"
    activity = {"activity_id": "file-1", "kind": "tool", "status": "completed", "conversation_turn_id": "turn-1",
                "subject": "workspace.write_file", "subject_i18n": {"zh": "已写入报价文件", "en": "Wrote quotation file"},
                "summary_i18n": {"zh": "报价.txt", "en": "quotation.txt"}, "detail": {"error": "PRIVATE_DIAGNOSTIC"}, "references": []}

    async def api(route):
        path = route.request.url.split("/api/", 1)[-1].split("?", 1)[0]
        if path == "user/profile":
            data = {"user_id": "test-user", "username": "Test"}
        elif path == "sessions/test-session":
            data = {"session_info": {"title": "报价核对"}, "messages": [
                {"id": "question", "role": "user", "content": "核对报价"},
                {"id": "answer", "role": "assistant", "content": "<thinking>旧版推理。</thinking>报价文件已写入。", "conversation_turn_id": "turn-1", "reasoning_tree_id": "tree-1",
                 "reasoning_steps": [{"step_id": "one", "source": "provider", "content": thought},
                                     {"step_id": "two", "source": "provider", "content": '{"action":"tool_call","needs_memory":true}'}]}]}
        elif path == "reasoning/tree/tree-1":
            tree_reads.append(path)
            data = {"nodes": [{"node_id": "thinking", "kind": "think", "status": "succeeded", "summary": '{"summary":"应先核对来源。","needs_memory":true}'},
                              {"node_id": "memory", "kind": "memory", "status": "succeeded", "observation": '{"needs_memory":true}'}]}
        elif path == "workbench/stream":
            await route.fulfill(content_type="text/event-stream", body=f'event: snapshot\ndata: {json.dumps({"timeline": [activity], "scope": {"session_id": "test-session"}})}\n\n')
            return
        else:
            data = {}
        await route.fulfill(json=data)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": 900})
            await page.add_init_script("localStorage.setItem('auth_token','test-only-token');if(!localStorage.getItem('promethea_ui_lang'))localStorage.setItem('promethea_ui_lang','zh')")
            await page.route("**/api/**", api)
            await page.goto(base + "/tests/message-content.html?chat")
            await expect(page.get_by_text("报价文件已写入。", exact=True)).to_be_visible()
            process = page.locator('.turn-process')
            await expect(process.get_by_text("已写入报价文件", exact=True)).to_be_visible()
            await expect(page.get_by_text("workspace.write_file", exact=True)).to_have_count(0)
            assert tree_reads == []
            await process.get_by_role("button", name="工作过程", exact=False).click()
            assert tree_reads == []
            await expect(page.get_by_text("旧版推理。", exact=True)).to_have_count(0)
            await process.get_by_role("button", name="推理过程", exact=True).click()
            step = process.get_by_role("button", name="模型推理 1", exact=True)
            await expect(step).to_be_visible()
            await expect(process.get_by_role("button", name="推理步骤 3", exact=True)).to_be_visible()
            assert len(tree_reads) == 1
            await step.click()
            await expect(page.get_by_text("先核对报价的数量。", exact=False)).to_be_visible()
            await expect(page.get_by_text("完整推理末尾", exact=False)).to_have_count(0)
            assert "needs_memory" not in await process.inner_text()
            assert "PRIVATE_DIAGNOSTIC" not in await process.inner_text()
            output = Path('.tmp/process-qa')
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f'process-zh-{width}.png'), full_page=True)
            await page.evaluate("window.setTestLanguage('en')")
            await expect(process.get_by_role("button", name="Work process", exact=True)).to_be_visible()
            await expect(process.get_by_text("Wrote quotation file", exact=True)).to_be_visible()
            await expect(process.get_by_role("button", name="Next", exact=True)).to_be_visible()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=str(output / f'process-{width}.png'), full_page=True)
            await process.get_by_role("button", name="Work process", exact=True).click()
            await expect(page.get_by_text("先核对报价的数量。", exact=False)).to_have_count(0)
            await page.reload()
            await expect(page.get_by_role("button", name="Work process", exact=False)).to_have_attribute("aria-expanded", "false")
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
        elif path == "voice/status":
            endpoint = {"provider": "disabled", "model": "", "base_url": "", "configured": False, "api_key_configured": False}
            data = {"stt": endpoint, "tts": endpoint, "speak_replies": False}
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
