"""Production frontend operations, with no personal data or live Runtime calls."""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]
BASE = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185").rstrip("/")


async def test_search_selects_exact_file_and_upload_failure_preserves_selection():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1536, "height": 960})
            _, _, errors = await prepare(page)
            files = [{"file_id": "first", "filename": "notes.md", "bytes": 420, "preview": "第一份材料"}, {"file_id": "target", "filename": "notes.md", "bytes": 1024, "snippet": "这才是搜索命中的认知材料"}]
            uploads = []

            async def api(route):
                path = urlparse(route.request.url).path
                if path == "/api/search":
                    await route.fulfill(json={"results": {"sessions": [], "files": [files[1]]}})
                elif path == "/api/files":
                    await route.fulfill(json={"files": files})
                elif path == "/api/files/upload":
                    uploads.append(route.request.post_data)
                    if len(uploads) == 1:
                        await route.fulfill(status=500, json={"error_detail": {"message": "文件保存失败"}})
                    else:
                        await route.fulfill(json={"file": {"file_id": "uploaded", "filename": "new.md", "bytes": 4, "modality": "text"}})
                else:
                    await route.fallback()

            await page.route("**/api/**", api)
            await page.goto(BASE)
            await page.get_by_role("navigation").get_by_role("button", name="搜索", exact=True).click()
            await page.get_by_placeholder("搜索会话和文件...").fill("认知")
            await page.locator(".feature-page").get_by_role("button", name="搜索", exact=True).click()
            await page.get_by_role("button", name="notes.md", exact=False).click()
            await expect(page.locator(".file-text-preview")).to_contain_text("这才是搜索命中的认知材料")
            await expect(page.locator(".file-row.is-selected")).to_contain_text("1.0 KB")
            output = Path(".tmp/frontend-qa")
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / "desktop-files.png"))
            await page.set_viewport_size({"width": 390, "height": 844})
            if await page.locator(".workspace-workbench").count():
                await page.get_by_role("button", name="收起工作台", exact=True).click()
            if await page.locator(".session-sidebar").count():
                await page.get_by_role("button", name="收起会话栏", exact=True).click()
            await expect(page.locator(".file-detail h2")).to_have_text("notes.md")
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=str(output / "mobile-files.png"))
            await page.get_by_role("button", name="附加到对话", exact=True).click()
            await expect(page.locator(".conversation-surface")).to_contain_text("notes.md")
            await page.get_by_role("navigation").get_by_role("button", name="文件", exact=True).click()
            await page.get_by_label("选择文件", exact=True).set_input_files({"name": "new.md", "mimeType": "text/markdown", "buffer": b"test"})
            await page.get_by_role("button", name="上传并附加", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("文件保存失败")
            await expect(page.locator(".file-upload-name")).to_have_text("new.md")
            await page.get_by_role("button", name="上传并附加", exact=True).click()
            await expect(page.locator(".conversation-surface")).to_contain_text("new.md")
            assert len(uploads) == 2
            assert not errors
        finally:
            await browser.close()


async def test_settings_load_retry_plugins_and_workspace_restore_clear_stale_chat():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 960})
            _, _, errors = await prepare(page)
            counts = {"config": 0, "plugin": 0, "restore": 0}
            enabled = False
            settings_open = False

            async def api(route):
                nonlocal enabled
                path = urlparse(route.request.url).path
                if path == "/api/config":
                    if settings_open:
                        counts["config"] += 1
                    await route.fulfill(status=503 if settings_open and counts["config"] == 1 else 200, json={"config": {"agent_name": "Promethea"}})
                elif path == "/api/plugins/catalog":
                    await route.fulfill(json={"plugins": [{"id": "demo", "name": "示例插件", "enabled": enabled}]})
                elif path == "/api/extensions/catalog":
                    await route.fulfill(json={"extensions": [{"id": "web", "name": "网页工具", "tool_count": 1, "callable_count": 1, "tools": [{"tool_id": "web.search", "callable_now": True, "description": "检索网页"}]}]})
                elif path == "/api/plugins/apply":
                    counts["plugin"] += 1
                    enabled = counts["plugin"] > 1
                    await route.fulfill(status=200 if enabled else 400, json={"enabled": enabled, "error_detail": {"message": "插件配置失败"}})
                elif path == "/api/personal/workspace/restore":
                    counts["restore"] += 1
                    assert "merge=false" in route.request.url
                    await route.fulfill(status=503 if counts["restore"] == 1 else 200, json={"applied": {"sessions": {"ok": True}}, "error": "恢复失败"})
                else:
                    await route.fallback()

            await page.route("**/api/**", api)
            await page.goto(BASE)
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await expect(page.locator(".chat-heading h1")).to_have_text("整理认知架构文章")
            settings_open = True
            await page.get_by_role("navigation").get_by_role("button", name="设置", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("设置加载失败")
            await expect(page.get_by_role("button", name="保存更改", exact=True)).to_have_count(0)
            await page.get_by_role("button", name="重试", exact=True).click()
            await page.get_by_text("高级能力与可见性", exact=True).click()
            await page.get_by_role("button", name="刷新工具目录", exact=True).click()
            toggle = page.get_by_role("checkbox", name="启用 示例插件", exact=True)
            await toggle.click()
            await expect(page.get_by_role("alert")).to_contain_text("插件配置失败")
            await expect(toggle).not_to_be_checked()
            await toggle.click()
            await expect(toggle).to_be_checked()
            await page.get_by_label("选择恢复包", exact=True).set_input_files({"name": "demo.promethea-workspace", "mimeType": "application/zip", "buffer": b"isolated fixture"})
            page.once("dialog", lambda dialog: dialog.dismiss())
            await page.get_by_role("button", name="恢复个人工作区", exact=True).click()
            assert counts["restore"] == 0
            page.once("dialog", lambda dialog: dialog.accept())
            await page.get_by_role("button", name="恢复个人工作区", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("恢复失败")
            await expect(page.get_by_role("button", name="恢复个人工作区", exact=True)).to_be_enabled()
            page.once("dialog", lambda dialog: dialog.accept())
            await page.get_by_role("button", name="恢复个人工作区", exact=True).click()
            await expect(page.get_by_text("工作区已恢复", exact=True)).to_be_visible()
            assert counts["config"] == 3
            await page.get_by_role("navigation").get_by_role("button", name="对话", exact=True).click()
            await expect(page.locator(".chat-heading h1")).to_have_text("新的对话")
            await expect(page.locator(".conversation-surface")).not_to_contain_text("请整理这份材料。")
            assert not errors
        finally:
            await browser.close()


async def test_auth_close_aborts_pending_sign_in_and_restores_focus():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 390, "height": 844})
            pending = asyncio.Queue()
            await page.add_init_script("localStorage.clear(); sessionStorage.clear(); localStorage.setItem('promethea_ui_lang','zh')")

            async def api(route):
                if urlparse(route.request.url).path == "/api/auth/login":
                    await pending.put(route)
                else:
                    await route.fulfill(json={})

            await page.route("**/api/**", api)
            await page.goto(BASE)
            opener = page.get_by_role("navigation").get_by_role("button", name="登录", exact=True)
            await opener.click()
            modal = page.get_by_role("dialog", name="登录", exact=True)
            await modal.get_by_label("用户名", exact=True).fill("fixture-user")
            await modal.get_by_label("密码", exact=True).fill("fixture-password")
            await modal.get_by_role("button", name="登录", exact=True).click()
            request = await asyncio.wait_for(pending.get(), 10)
            await page.keyboard.press("Tab")
            assert await modal.evaluate("node => node.contains(document.activeElement)")
            await page.keyboard.press("Escape")
            await expect(modal).to_have_count(0)
            await expect(opener).to_be_focused()
            await request.fulfill(json={"access_token": "stale", "user_id": "stale", "username": "Stale"})
            await page.wait_for_timeout(100)
            assert await page.evaluate("localStorage.getItem('auth_token') || sessionStorage.getItem('auth_token')") is None
            await opener.click()
            await expect(modal.get_by_label("用户名", exact=True)).to_be_editable()
            await page.locator(".feature-overlay").click(position={"x": 1, "y": 1})
            await expect(modal).to_have_count(0)
        finally:
            await browser.close()


async def test_avatar_mutation_failure_and_diagnostic_disclosure():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            _, _, errors = await prepare(page)
            diagnostics = []

            async def api(route):
                path = urlparse(route.request.url).path
                if path == "/api/avatar/current":
                    if route.request.method == "PUT":
                        await route.fulfill(status=500, json={"error": "fixture failure"})
                    else:
                        await route.fulfill(json={"avatar": {"avatar_id": "demo", "kind": "none", "enabled": True, "filename": "avatar.png"}})
                elif path == "/api/doctor":
                    diagnostics.append(path)
                    await route.fulfill(json={"status": "degraded", "checks": {"config_api": {"ok": True, "model": "fixture-model"}, "memory": {"ok": False, "issues": ["fixture connection failure"]}}})
                elif path == "/api/doctor/migrate-config":
                    await route.fulfill(status=503, json={"error": "fixture failure"})
                else:
                    await route.fallback()

            await page.route("**/api/**", api)
            await page.goto(BASE)
            await page.get_by_role("navigation").get_by_role("button", name="设置", exact=True).click()
            enabled = page.get_by_role("checkbox", name="启用形象", exact=True)
            await expect(enabled).to_be_checked()
            await enabled.click()
            await expect(page.get_by_role("alert")).to_contain_text("形象设置保存失败")
            await expect(enabled).to_be_checked()
            await page.get_by_role("navigation").get_by_role("button", name="诊断", exact=True).click()
            await expect(page.get_by_role("status", name="")).to_contain_text("部分服务异常")
            await expect(page.get_by_text("fixture connection failure", exact=True)).not_to_be_visible()
            await page.locator(".diagnostic-row").filter(has_text="记忆服务").locator("summary").click()
            await expect(page.get_by_text("fixture connection failure", exact=True)).to_be_visible()
            output = Path(".tmp/frontend-qa")
            await page.screenshot(path=str(output / "desktop-diagnostics.png"))
            before_reload = len(diagnostics)
            await page.get_by_role("button", name="重载配置", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("诊断请求失败")
            assert len(diagnostics) == before_reload
            assert not errors
        finally:
            await browser.close()
