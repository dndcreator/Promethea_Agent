"""No real credentials: sentinels prove the browser's observation boundary."""
import os
import ast
import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentkit.tools.computer.computer_control import ComputerControlService
from computer.browser import BrowserController
from computer.execution_context import bind_workspace


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in actual browser")
async def test_closed_active_page_recovers_without_replaying_navigation(tmp_path):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        controller = BrowserController(workspace_root=str(tmp_path))
        controller.browser = browser
        controller.context = await browser.new_context()
        controller.context.on("page", controller._register_page)
        controller._headless = True
        controller.is_initialized = True
        try:
            first = await controller.context.new_page()
            first_id = controller._register_page(first)
            second = await controller.context.new_page()
            second_id = controller._register_page(second)
            await second.set_content("<title>Retained page</title><button>Ready</button>")
            assert controller.page is first
            await first.close()  # Same lifecycle event as the user's manual tab closure.
            result = await controller.execute("get_title", {})
            assert result.success and result.result == "Retained page"
            assert controller.page is second
            assert first_id not in result.metadata["browser_state"]["open_tab_ids"]
            assert result.metadata["browser_state"]["active_tab_id"] == second_id
            tabs = await controller.execute("list_tabs", {})
            assert [row["tab_id"] for row in tabs.result] == [second_id]
            await second.close()
            missing = await controller.execute("get_title", {})
            assert not missing.success and "No open browser page" in missing.error
            assert not controller.context.pages, "a read must not silently reopen a closed window"
            opened = await controller.execute("new_tab", {})
            assert opened.success and opened.result["active"]
            assert opened.result["tab_id"] not in {first_id, second_id}
            snapshot = await controller.execute("snapshot", {})
            assert snapshot.success
            assert snapshot.result["browser_state"]["mode"] == "headless"
            assert snapshot.result["browser_state"]["user_visibility_verified"] is False
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in actual browser")
async def test_form_observations_never_echo_credentials(tmp_path, monkeypatch):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page()
            await page.set_content('''<label for="email">Email</label><input id="email" value="PRIVATE-EMAIL-SENTINEL">
                <label for="password">Password</label><input id="password" type="password" value="PRIVATE-PASSWORD-SENTINEL">
                <input type="hidden" value="PRIVATE-HIDDEN-SENTINEL"><textarea>PRIVATE-TEXTAREA-SENTINEL</textarea>
                <script>window.token="PRIVATE-SCRIPT-SENTINEL"</script><button>Continue</button>''')
            controller = BrowserController(workspace_root=str(tmp_path))
            controller.page = page
            html = await controller._get_content({"type": "html"})
            assert "PRIVATE-" not in html
            with pytest.raises(PermissionError, match="Protected credential"):
                await controller._type({"selector": "#password", "text": "UNSAFE-PLAINTEXT"})
            assert await page.locator("#password").input_value() == "PRIVATE-PASSWORD-SENTINEL"
            assert "DO-NOT-ECHO" not in await controller._type({"selector": "#email", "text": "DO-NOT-ECHO"})
            service = ComputerControlService()
            async def execute(capability, action, params=None):
                assert action == "snapshot"
                return {"ok": True, "result": await controller._snapshot(params)}
            monkeypatch.setattr(service, "_execute_action_raw", execute)
            result = await service.browser_action(action="snapshot")
            assert "PRIVATE-" not in result and "DO-NOT-ECHO" not in result
            assert "Password" in result and "Email" in result
            assert "input_type" in result and "filled" in result
            candidates = await service._find_browser_candidates("Email")
            assert candidates["candidates"]
            assert "PRIVATE-" not in str(candidates) and "DO-NOT-ECHO" not in str(candidates)
            await page.screenshot(path=str(tmp_path / "form.png"))
        finally:
            await browser.close()


def test_browser_manifest_declares_actual_call_schema():
    import json
    path = Path(__file__).resolve().parents[1] / "agentkit/tools/computer/agent-manifest.json"
    command = json.loads(path.read_text())["capabilities"]["invocation_commands"][0]
    assert command["inputSchema"]["required"] == ["action"]
    assert {"ref", "selector", "text", "max_nodes"} <= command["inputSchema"]["properties"].keys()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in actual browser")
async def test_frame_only_page_and_screenshot_are_observable(tmp_path, monkeypatch):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page()
            await page.set_content('<iframe title="Embedded workspace" srcdoc="&lt;button&gt;Inside&lt;/button&gt;"></iframe>')
            controller = BrowserController(workspace_root=str(tmp_path))
            controller.page = page
            service = ComputerControlService()

            async def execute(capability, action, params=None):
                if action == "snapshot":
                    return {"ok": True, "result": await controller._snapshot(params)}
                assert action == "screenshot"
                return {"ok": True, "result": await controller._screenshot(params or {})}

            monkeypatch.setattr(service, "_execute_action_raw", execute)
            with bind_workspace(SimpleNamespace(user_id="test-user", workspace_id="test", root_path=tmp_path)):
                snapshot = ast.literal_eval((await service.browser_action(action="snapshot")).split("Result: ", 1)[1])
                assert snapshot["count"] == 0
                assert snapshot["node_scope"] == "main_document"
                assert snapshot["frame_count"] == 1
                assert snapshot["frames"][0]["title"] == "Embedded workspace"
                assert snapshot["frames"][0]["visible"]
                shot = await service.browser_action(action="screenshot")
            metadata = ast.literal_eval(shot.split("Result: ", 1)[1].strip())
            image = Path(metadata["image_path"])
            assert image.resolve().is_relative_to(tmp_path.resolve())
            assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            assert image.stat().st_size == metadata["size"]
            assert metadata["image_delivery"] == "workspace_file"
            assert "screenshot" not in metadata and len(shot) < 1000
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_screenshot_export_requires_owner_and_valid_image(tmp_path, monkeypatch):
    from PIL import Image
    buffer = BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    service = ComputerControlService()

    async def execute(*args, **kwargs):
        return {"ok": True, "result": {"screenshot": encoded, "format": "png"}}

    monkeypatch.setattr(service, "_execute_action_raw", execute)
    assert "trusted workspace" in await service.browser_action(action="screenshot")
    with bind_workspace(SimpleNamespace(user_id="owner", workspace_id="test", root_path=tmp_path)):
        first = await service.browser_action(action="screenshot")
        second = await service.browser_action(action="screenshot")
        assert first != second and encoded not in first
        encoded = "not-an-image"
        assert (await service.browser_action(action="screenshot")).startswith("ERROR:")
    assert len(list(tmp_path.rglob("*.png"))) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["screenshot", "record_screenshot"])
async def test_browser_screenshot_can_return_pixels_and_artifact_in_one_observation(tmp_path, monkeypatch, action):
    from PIL import Image
    from gateway.action.observation import RuntimeObservation
    from gateway.model_protocol import request_fields

    buffer = BytesIO()
    Image.new("RGB", (64, 64), "red").save(buffer, format="PNG")
    service = ComputerControlService()

    async def execute(_, requested, params):
        assert requested == action and "include_image" not in params
        return {"ok": True, "result": {"screenshot": base64.b64encode(buffer.getvalue()).decode("ascii"), "end_ms": 42}}

    monkeypatch.setattr(service, "_execute_action_raw", execute)
    with bind_workspace(SimpleNamespace(user_id="owner", workspace_id="test", root_path=tmp_path)):
        result = await service.browser_action(action=action, include_image=True)
    assert Path(result.value["image_path"]).read_bytes() == buffer.getvalue()
    assert result.value["end_ms"] == 42
    observation = RuntimeObservation.from_result(action_loop_id="a", model_step_id="m", tool_call_id="t",
        tool_name=result.tool_name, result=result, capability_snapshot_id=None, scope={})
    request = request_fields([{"role": "user", "content": observation.model_content()}], {"protocol": "prompt_json"})
    _, pixels = request["messages"][0]["content"]
    assert set(pixels) == {"type", "image_url"}
    jpeg = base64.b64decode(pixels["image_url"]["url"].split(",", 1)[1])
    with Image.open(BytesIO(jpeg)) as image:
        assert image.getpixel((0, 0))[0] > 240
