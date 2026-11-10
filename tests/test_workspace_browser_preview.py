import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentkit.security.sandbox import get_sandbox_policy
from computer.browser import BrowserController
from computer.browser_preview import WorkspaceBrowserPreview
from computer.runtime import ComputerRuntime
from gateway.capability_service import CapabilityService, ToolInvocationContext
from gateway.workspace_service import WorkspaceService


@pytest.mark.parametrize("path", ["../outside.html", "a/../index.html", ".private/index.html",
                                  "C:/index.html", r"\\host\index.html", "index.html:secret"])
def test_preview_rejects_non_public_workspace_paths(tmp_path, path):
    preview = WorkspaceBrowserPreview(None, tmp_path, get_sandbox_policy())
    with pytest.raises(ValueError, match="workspace-relative"):
        preview._file(tmp_path, path)


def test_preview_uses_existing_tool_with_workspace_effect():
    manifest = Path(__file__).resolve().parents[1] / "agentkit/tools/computer/agent-manifest.json"
    spec = json.loads(manifest.read_text())["capabilities"]["invocation_commands"][0]
    assert "preview" in spec["sideEffectSelector"]["groups"]["workspace_write"]
    assert "reload" in spec["inputSchema"]["properties"]["operation"]["enum"]
    assert "click" not in spec["sideEffectSelector"]["groups"]["workspace_write"]
    service = CapabilityService()
    service.ensure_discovered_tools()
    assert not service.requires_confirmation("computer_control.browser_action", {"action": "preview", "operation": "click"})
    assert service.requires_confirmation("computer_control.browser_action", {"action": "click"})


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in actual browser")
async def test_workspace_preview_interactions_reload_and_isolation(tmp_path, monkeypatch):
    from playwright.async_api import async_playwright

    workspaces = WorkspaceService(base_dir=str(tmp_path))
    handle = workspaces.resolve_workspace_handle(user_id="alice", workspace_id="preview-test")
    root = Path(handle.root_path)
    (root / "index.html").write_text('''<form><input id="task" required><button>Add</button></form>
      <label><input id="done" type="checkbox"><span></span></label>
      <button id="delete">Delete</button><div id="network"></div><script src="app.js"></script>''', encoding="utf-8")
    (root / "app.js").write_text('''
      const task = document.querySelector('#task'), done = document.querySelector('#done');
      const render = () => { document.querySelector('span').textContent = localStorage.task || '';
        done.checked = localStorage.done === 'true'; };
      document.querySelector('form').onsubmit = e => {e.preventDefault(); localStorage.task = task.value; render();};
      done.onchange = () => {localStorage.done = done.checked;};
      document.querySelector('#delete').onclick = () => {localStorage.clear(); render();};
      render();
      fetch('http://127.0.0.1:1/private').catch(() => {document.querySelector('#network').textContent = 'Network blocked';});
    ''', encoding="utf-8")
    (root / "other.html").write_text("<p>Other app</p>", encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"],
                                                     headless=True, chromium_sandbox=True)
        controller = BrowserController(workspace_root=str(root))
        controller.browser = browser
        controller.context = await browser.new_context()
        controller.is_initialized = True
        runtime = ComputerRuntime({"browser": lambda **_: controller})
        service = CapabilityService(computer_runtime=runtime, workspace_service=workspaces)
        service.ensure_discovered_tools()
        monkeypatch.setattr("gateway.http.dispatcher.get_gateway_server", lambda: SimpleNamespace(capability_service=service))
        try:
            ordinary = await controller.context.new_page()
            controller._register_page(ordinary)
            await ordinary.set_content("<title>Ordinary tab</title>")
            denied = await controller.execute("navigate", {"url": (root / "index.html").as_uri()})
            assert not denied.success

            async def preview(operation, **kwargs):
                result = await controller.execute("preview", {"operation": operation, **kwargs})
                assert result.success, result.error
                return result.result

            opened = await service.call_tool("computer_control.browser_action", {"action": "preview", "path": "index.html"},
                                             ctx=ToolInvocationContext(user_id="alice", session_id="preview-test"))
            assert "SUCCESS" in str(opened) and "#task" in str(opened)
            await preview("fill", selector="#task", text="Review proposal")
            await preview("press", selector="#task", key="Enter")
            checked = await preview("click", selector="#done")
            assert any(node.get("checked") for node in checked["nodes"] if node["selector"] == "#done")
            reloaded = await preview("reload")
            assert "Review proposal" in reloaded["text"] and "Network blocked" in reloaded["text"]
            assert any(node.get("checked") for node in reloaded["nodes"] if node["selector"] == "#done")
            await preview("click", selector="#delete")
            assert "Review proposal" not in (await preview("reload"))["text"]

            await preview("fill", selector="#task", text="App-specific state")
            await preview("press", selector="#task", key="Enter")
            await preview("open", path="other.html")
            assert "Other app" in (await preview("snapshot"))["text"]
            assert await controller._preview.page.evaluate("localStorage.length") == 0
            await preview("close")
            assert controller.page is ordinary and await ordinary.title() == "Ordinary tab"
        finally:
            await runtime.close()
            if controller.is_initialized:
                await controller.cleanup()
