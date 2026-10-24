"""Exercise the production shell with isolated, synthetic public API responses."""
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


async def prepare(page):
    projects = [{"project_id": "research", "name": "资料研究", "created_at": "2026-10-20T00:00:00Z", "updated_at": "2026-10-20T00:00:00Z", "session_ids": ["article"]}]
    sessions = [{"session_id": "article", "title": "整理认知架构文章", "pinned": False}, {"session_id": "desktop", "title": "统计桌面图标", "pinned": False}]
    task = {"task_id": "research-task", "title": "整理研究材料", "objective": "查阅公开资料并整理为文章草稿", "status": "running", "revision": 3, "session_ids": ["article"], "runs": [{"run_id": "old-run", "status": "completed", "started_at": "2026-10-19T01:00:00Z"}, {"run_id": "task-run", "status": "running", "started_at": "2026-10-20T01:00:00Z"}]}
    calls = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    await page.add_init_script("if (window === window.top) { localStorage.setItem('auth_token','test-only-token'); localStorage.setItem('promethea_ui_lang','zh') }")

    async def api(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path.removeprefix("/api/")
        calls.append((request.method, path, parse_qs(parsed.query)))
        data = {}
        if path == "user/profile":
            data = {"user_id": "demo-user", "username": "Shepard", "agent_name": "Promethea"}
        elif path == "sessions":
            data = {"sessions": sessions}
        elif path.startswith("sessions/") and path.endswith("/project"):
            session_id = path.split("/")[1]
            for project in projects:
                project["session_ids"] = [sid for sid in project["session_ids"] if sid != session_id]
                if project["project_id"] == request.post_data_json["project_id"]:
                    project["session_ids"].append(session_id)
            await route.fulfill(status=204)
            return
        elif path.startswith("sessions/") and path.endswith("/pin"):
            sid = path.split("/")[1]
            for session in sessions:
                if session["session_id"] == sid:
                    session["pinned"] = request.post_data_json["pinned"]
        elif path.startswith("sessions/"):
            sid = path.split("/")[1]
            title = next((s["title"] for s in sessions if s["session_id"] == sid), "新建草稿")
            data = {"session_info": {"title": title}, "messages": [{"id": sid + "-user", "role": "user", "content": "请整理这份材料。"}, {"id": sid + "-assistant", "role": "assistant", "content": "我已检查材料，建议先区分记忆存储与主动认知，再梳理执行边界。参考：[架构资料](https://example.org/architecture)。"}]}
        elif path == "projects":
            if request.method == "POST":
                project = {"project_id": "new-project", "name": request.post_data_json["name"], "session_ids": [], "created_at": "2026-10-20T00:00:00Z", "updated_at": "2026-10-20T00:00:00Z"}
                projects.append(project)
                await route.fulfill(status=201, json=project)
                return
            data = {"projects": projects}
        elif path.startswith("projects/"):
            project_id = path.split("/")[1]
            if request.method == "DELETE":
                projects[:] = [project for project in projects if project["project_id"] != project_id]
                await route.fulfill(status=204)
                return
            project = next(project for project in projects if project["project_id"] == project_id)
            project["name"] = request.post_data_json["name"]
            data = project
        elif path == "tasks":
            data = {"tasks": [task]}
        elif path.startswith("tasks/"):
            if path.endswith("/pause"):
                assert request.post_data_json["expected_revision"] == task["revision"]
                task["status"] = "paused"
                task["revision"] += 1
            data = {"task": task}
        elif path == "workbench/stream":
            query = parse_qs(parsed.query)
            scope = {"user_id": "demo-user", "session_id": (query.get("session_id") or [None])[0], "task_id": (query.get("task_id") or [None])[0], "run_id": (query.get("run_id") or [None])[0]}
            activity = {"activity_id": "fetch-1", "kind": "tool", "status": "succeeded", "seq": 1, "subject": "Fetch page", "subject_i18n": {"zh": "读取网页 · example.org", "en": "Fetch page · example.org"}, "summary_i18n": {"zh": "已读取架构资料", "en": "Read architecture notes"}, "occurred_at": "2026-10-20T01:00:01Z", "references": [{"reference_id": "url", "kind": "url", "target": "https://example.org/architecture", "label": "example.org/architecture"}, {"reference_id": "file", "kind": "artifact", "target": "draft.md", "label": "文章草稿.md", "metadata": {"workspace_id": "article"}}, {"reference_id": "canvas", "kind": "canvas", "target": "calculator", "label": "交互计算器", "metadata": {"workspace_id": "article"}}]}
            snapshot = {"scope": scope, "timeline": [activity], "cursor": 1, "memory_proposals": [{"proposal_id": "review", "session_id": scope["session_id"]}], "task": task if scope["task_id"] else None, "runs": [run for run in task["runs"] if run["run_id"] == scope["run_id"]]}
            await route.fulfill(content_type="text/event-stream", body=f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n")
            return
        elif path == "workbench/artifact":
            await route.fulfill(content_type="text/markdown", body="# 文章草稿\n\n这里是实际产物的预览。")
            return
        elif path == "status":
            data = {"conversation_ready": True, "memory_sync": {"pending": 0}}
        elif path == "health/memory":
            data = {"ready": True, "active_backend": "neo4j"}
        elif path == "config/secrets":
            data = {"secrets": {"api": {"model": "deepseek-chat"}}}
        elif path == "channels":
            data = []
        elif path == "memory/write-proposals":
            data = {"proposals": [{"proposal_id": "review", "content": "用户倾向于简洁的界面。", "memory_type": "semantic", "conflict_candidates": ["用户喜欢详细的说明。"]}]}
        elif "write-proposals/review/decision" in path:
            await route.fulfill(status=500, json={"error_detail": {"message": "确认请求失败"}})
            return
        elif path == "welcome":
            data = {"greeting": "晚上好，Shepard。", "context_hint": "上次的架构文章，可以接着整理。", "suggested_actions": ["继续梳理认知机制", "看看研究任务", "整理今天的材料"]}
        elif path == "memory/cognition":
            texts = ["用户重视简洁、可控的交互", "记忆存储与主动认知保持分离", "当前在整理认知架构文章", "工具执行结果由 Runtime 确认", "长期任务可以暂停与恢复", "会话是交流入口，不是任务本体", "用户偏好明确的执行状态", "项目用于组织相关对话", "需要保留失败后的上下文", "对暂时性的计划保留不确定性", "已完成资料归档", "界面不应暴露内部调试结构"]
            data = {"user_id": "demo-user", "cognition": {"user_id": "demo-user", "items": [{"cognition_id": str(index), "content": text, "domain": "user", "state": "current", "importance": .6} for index, text in enumerate(texts)], "stats": {"states": {"current": len(texts)}}}}
        elif path == "canvas/environments":
            workspace = (parse_qs(parsed.query).get("workspace_id") or ["default"])[0]
            data = {"workspace_id": workspace, "environments": [] if workspace == "_canvas_library" else [{"workspace_id": workspace, "environment_id": "calculator", "name": "交互计算器", "kind": "static", "lifetime": "session", "preview_url": "/test-canvas", "content_revision": "v1"}]}
        elif "canvas" in path:
            data = {"environments": []}
        await route.fulfill(json=data)

    await page.route("**/api/**", api)
    await page.route("**/test-canvas", lambda route: route.fulfill(content_type="text/html", body='<html lang="zh"><meta charset="utf-8"><body style="font:14px system-ui;padding:24px"><h2>交互计算器</h2><label>数值 <input id="value" type="number" value="2"></label><button onclick="document.querySelector(\'output\').textContent=Number(document.querySelector(\'input\').value)*2">计算</button><output style="display:block;margin-top:20px">4</output></body></html>'))
    return projects, calls, errors


async def test_production_shell_projects_navigation_workbench_and_tasks():
    from playwright.async_api import async_playwright, expect
    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185").rstrip("/")
    output = Path(".tmp/frontend-qa")
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1536, "height": 960}, device_scale_factor=1)
            projects, calls, errors = await prepare(page)
            await page.goto(base)
            await expect(page.get_by_role("button", name="整理认知架构文章", exact=True)).to_be_visible()
            await page.get_by_placeholder("输入消息").fill("这段草稿不能丢")
            await page.get_by_role("button", name="任务", exact=True).click()
            await page.get_by_role("button", name="整理研究材料", exact=False).click()
            await expect(page.locator(".task-detail h2")).to_have_text("整理研究材料")
            await expect(page.locator('.task-detail').get_by_role('button', name='整理认知架构文章', exact=True)).to_be_visible()
            await page.get_by_role("button", name="暂停", exact=True).click()
            await expect(page.locator(".task-detail-heading")).to_contain_text("已暂停")
            await page.get_by_role("button", name="对话", exact=True).click()
            await expect(page.get_by_placeholder("输入消息")).to_have_value("这段草稿不能丢")
            await page.get_by_role("button", name="新建项目", exact=True).click()
            await page.get_by_role("dialog", name="新建项目").get_by_label("名称").fill("写作计划")
            await page.get_by_role("button", name="保存", exact=True).click()
            await expect(page.get_by_role("button", name="写作计划", exact=True)).to_be_visible()
            assert len(projects) == 2
            await page.get_by_role("button", name="管理会话：统计桌面图标", exact=True).click()
            await page.get_by_label("所属项目", exact=True).select_option("new-project")
            await page.get_by_role("button", name="保存", exact=True).click()
            await expect(page.locator(".project-group").filter(has_text="写作计划").get_by_text("统计桌面图标", exact=True)).to_be_visible()
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await expect(page.locator(".chat-heading h1")).to_have_text("整理认知架构文章")
            await expect(page.get_by_role("link", name="架构资料", exact=True)).to_have_attribute("href", "https://example.org/architecture")
            await expect(page.get_by_role("button", name="文章草稿.md", exact=True)).to_be_visible()
            await page.screenshot(path=str(output / "desktop-chat.png"))
            await page.get_by_role("button", name="文章草稿.md", exact=True).click()
            await expect(page.locator(".artifact-text")).to_contain_text("文章草稿")
            await page.screenshot(path=str(output / "desktop-artifact.png"))
            await page.get_by_role("button", name="返回工作", exact=True).click()
            await page.get_by_role("button", name="交互计算器", exact=True).click()
            frame = page.frame_locator('iframe[title="交互计算器"]')
            await frame.get_by_label("数值", exact=True).fill("7")
            await frame.get_by_role("button", name="计算", exact=True).click()
            await expect(frame.locator("output")).to_have_text("14")
            await page.screenshot(path=str(output / "desktop-canvas.png"))
            await page.get_by_role("tab", name="活动", exact=False).click()
            await page.get_by_role("button", name="读取网页 · example.org", exact=False).click()
            await expect(page.get_by_text("技术详情", exact=True)).to_be_visible()
            await page.screenshot(path=str(output / "desktop-activity.png"))
            await page.get_by_role("tab", name="工作", exact=True).click()
            await expect(frame.get_by_label("数值", exact=True)).to_have_value("7")
            await page.get_by_role("button", name="收起工作台", exact=True).click()
            await expect(page.get_by_role("button", name="打开记忆", exact=True)).to_be_visible()
            await page.get_by_role("button", name="打开记忆", exact=True).click()
            await expect(page.get_by_role("button", name="确认并更新", exact=True)).to_be_visible()
            await page.get_by_role("button", name="确认并更新", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("确认请求失败")
            await expect(page.get_by_role("button", name="确认并更新", exact=True)).to_be_visible()
            await page.screenshot(path=str(output / "desktop-review.png"))
            await page.get_by_role("button", name="任务", exact=True).click()
            await page.get_by_role("button", name="整理研究材料", exact=False).click()
            await page.get_by_role("button", name="在工作台观察", exact=True).click()
            await expect(page.locator(".observed-task")).to_contain_text("整理研究材料")
            await expect(page.locator(".runtime-workbench")).to_have_count(1)
            assert any(query.get("task_id") == ["research-task"] for _, path, query in calls if path == "workbench/stream")
            await page.get_by_role('button', name='查看运行 1', exact=True).click()
            await expect(page.locator('.observed-task')).to_contain_text('运行 1')
            await expect(page.locator('.runtime-workbench').get_by_text('已完成', exact=True)).to_be_visible()
            await expect(page.locator('.runtime-workbench').get_by_role('button', name='停止任务', exact=True)).to_have_count(0)
            assert any(query.get('run_id') == ['old-run'] for _, path, query in calls if path == 'workbench/stream')
            await page.screenshot(path=str(output / 'desktop-task-run.png'))
            await page.get_by_role('button', name='整个任务', exact=True).click()
            await expect(page.locator('.runtime-workbench').get_by_role('button', name='停止任务', exact=True)).to_be_visible()
            assert not errors
        finally:
            await browser.close()


async def test_production_mobile_drawers_and_no_horizontal_overflow():
    from playwright.async_api import async_playwright, expect
    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5185").rstrip("/")
    output = Path(".tmp/frontend-qa")
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
            _, _, errors = await prepare(page)
            await page.goto(base)
            await expect(page.get_by_placeholder("输入消息")).to_be_visible()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=str(output / "mobile-home.png"))
            await page.get_by_role("button", name="展开会话栏", exact=True).click()
            await expect(page.get_by_role("button", name="整理认知架构文章", exact=True)).to_be_visible()
            await page.screenshot(path=str(output / "mobile-sidebar.png"))
            await page.get_by_role("button", name="整理认知架构文章", exact=True).click()
            await expect(page.locator(".session-sidebar")).to_have_count(0)
            await page.get_by_role("button", name="切换工作台", exact=True).click()
            await expect(page.locator(".runtime-workbench")).to_have_count(1)
            await page.screenshot(path=str(output / "mobile-workbench.png"))
            await page.get_by_role("button", name="收起工作台", exact=True).click()
            await expect(page.locator(".runtime-workbench")).to_have_count(0)
            await page.get_by_role("button", name="任务", exact=True).click()
            await page.get_by_role("button", name="整理研究材料", exact=False).click()
            await expect(page.get_by_role("button", name="在工作台观察", exact=True)).to_be_visible()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=str(output / "mobile-task.png"))
            assert not errors
        finally:
            await browser.close()
