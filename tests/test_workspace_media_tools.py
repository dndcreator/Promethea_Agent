import base64
import json
import os
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from agentkit.security.sandbox import SandboxPolicy
from agentkit.tools.standard.media_tools import WorkspaceImageViewTool, VideoEditTool, VideoFrameTool, VideoInspectTool
from computer.browser_recording import BrowserRecording
from gateway.action.observation import RuntimeObservation
from gateway.capability_service import CapabilityService, ToolInvocationContext
from gateway.model_protocol import request_fields, response_fields
from gateway.runtime_io import ContextCompiler
from gateway.workspace_service import WorkspaceService


def owned_workspace(tmp_path):
    service = WorkspaceService(base_dir=str(tmp_path))
    ctx = ToolInvocationContext(user_id="alice", session_id="media")
    return service, ctx, Path(service.resolve_workspace_handle(user_id="alice", workspace_id="media").root_path)


@pytest.mark.asyncio
async def test_image_tool_reaches_provider_as_pixels_without_repeating_history(tmp_path):
    service, ctx, root = owned_workspace(tmp_path)
    Image.new("RGB", (100, 100), "red").save(root / "test.png")
    tool = WorkspaceImageViewTool(service)
    result = await tool.invoke({"path": str(root / "test.png")}, ctx)
    with pytest.raises(ValueError):
        await tool.invoke({"path": "../test.png"}, ctx)
    with pytest.raises(PermissionError):
        await tool.invoke({"path": "test.png"})
    obs = RuntimeObservation.from_result(action_loop_id="a", model_step_id="m", tool_call_id="t",
                                        tool_name=tool.name, result=result, capability_snapshot_id=None, scope={})
    following = {**obs.as_dict(), "observation_id": "next"}
    next_fact = {"type": "text", "text": json.dumps({"observation_id": "next", "result": "next", "error": None})}
    messages = [{"role": "user", "content": obs.model_content()}, {"role": "user", "content": [next_fact, *result.content]}]
    compiled = ContextCompiler.project_observations(messages, [obs.as_dict(), following], per_result_chars=2000, total_chars=4000)
    wire = request_fields(compiled, {"protocol": "prompt_json"})["messages"]
    assert len(wire[0]["content"]) == 1
    picture = wire[1]["content"][1]
    assert set(picture) == {"type", "image_url"}
    data = base64.b64decode(picture["image_url"]["url"].split(",", 1)[1])
    with Image.open(BytesIO(data)) as image:
        assert image.getpixel((1, 1))[0] > 240
    packet = {"role": "assistant", "tool_calls": [{"id": "t", "type": "function", "function": {
        "name": "tool_call", "arguments": json.dumps({"tool_name": "image.view", "args": {"path": "test.png"}}),
    }}]}
    accepted = response_fields(packet)
    native = request_fields([
        {"role": "assistant", "content": accepted["content"], "_model_step_id": "m"},
        {"role": "user", "content": obs.model_content()},
    ], {"protocol": "native", "wire_history": {"m": {"message": packet, "bindings": accepted["native_bindings"]}},
        "observations": [obs.as_dict()]})["messages"]
    assert [row["role"] for row in native] == ["assistant", "tool", "user"]
    assert native[1]["tool_call_id"] == "t" and "base64" not in native[1]["content"]
    assert native[2]["content"] == [picture]


def test_media_uses_standard_registry_and_recorded_inputs_keep_policy(tmp_path):
    workspace, _, _ = owned_workspace(tmp_path)
    service = CapabilityService(workspace_service=workspace)
    service.bind_tool_runtime(workspace_service=workspace)
    service.ensure_discovered_tools()
    registered = {spec.full_name for spec in service.tool_registry.list_specs()}
    assert {"image.view", "video.inspect", "video.frame", "video.edit"} <= registered
    assert service.requires_confirmation("computer_control.browser_action", {"action": "record_press", "keys": ["ArrowUp"]})
    assert not service.requires_confirmation("computer_control.browser_action", {"action": "record_stop"})


def make_source(av, path):
    with av.open(str(path), "w") as output:
        track = output.add_stream("libx264", rate=25)
        track.width, track.height, track.pix_fmt = 160, 90, "yuv420p"
        for i in range(50):
            frame = av.VideoFrame.from_image(Image.new("RGB", (160, 90), "red" if i < 25 else "blue"))
            for packet in track.encode(frame):
                output.mux(packet)
        for packet in track.encode():
            output.mux(packet)


@pytest.mark.asyncio
async def test_video_edits_real_clips_in_selected_order_and_decodes_output(tmp_path):
    av = pytest.importorskip("av")
    service, ctx, root = owned_workspace(tmp_path)
    make_source(av, root / "input.mp4")
    edit = VideoEditTool(service)
    args = {"output": "out.mp4", "segments": [{"path": "input.mp4", "start_ms": start, "end_ms": start + 400}
                                               for start in (1200, 200)]}
    result = await edit.invoke(args, ctx)
    assert result["duration_ms"] == 800 and result["frame_count"] == 20
    probe = await VideoInspectTool(service).invoke({"path": "out.mp4"}, ctx)
    assert probe["duration_ms"] == 800 and probe["first_frame_decoded"] is True
    with av.open(str(root / "out.mp4")) as output:
        frames = list(output.decode(video=0))
    assert frames[0].to_image().getpixel((640, 360))[2] > 235
    assert frames[-1].to_image().getpixel((640, 360))[0] > 235
    frame = await VideoFrameTool(service).invoke({"path": "out.mp4", "at_ms": 400}, ctx)
    assert frame.value["frame_ms"] == 400 and frame.content[0]["type"] == "image_url"
    with pytest.raises(ValueError, match="new .mp4"):
        await edit.invoke(args, ctx)
    invalid = {"output": "incomplete.mp4", "segments": [{"path": "input.mp4", "start_ms": 0, "end_ms": 3000}]}
    with pytest.raises(ValueError, match="known source duration"):
        await edit.invoke(invalid, ctx)
    assert sorted(path.name for path in root.iterdir()) == ["input.mp4", "out.mp4"]


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("PROMETHEA_TEST_MEDIA_RECORDING"), reason="opt-in with Playwright FFmpeg installed")
async def test_real_edge_finalizes_isolated_recording_for_workspace_edit(tmp_path, monkeypatch):
    from playwright.async_api import async_playwright

    pytest.importorskip("av")
    workspace, ctx, root = owned_workspace(tmp_path)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="msedge", headless=True, chromium_sandbox=True)
        recording = BrowserRecording(browser, root, SandboxPolicy())
        try:
            with pytest.raises(PermissionError):
                await recording.execute("record_start", {"url": "http://127.0.0.1/"})

            async def serve_fixture(route):
                await route.fulfill(content_type="text/html", body="<p>Ready</p><script>onkeydown=e=>document.querySelector('p').textContent=e.key</script>")

            monkeypatch.setattr(recording, "_route", serve_fixture)
            await recording.execute("record_start", {"url": "https://fixture.invalid/", "duration_s": 10})
            await recording.execute("record_press", {"keys": ["ArrowLeft", "ArrowRight"]})
            state = await recording.execute("record_snapshot", {})
            assert state["text"] == "ArrowRight" and state["end_ms"] >= state["start_ms"]
            receipt = await recording.execute("record_stop", {})
            assert await recording.execute("record_stop", {}) == receipt
            assert not recording.active and not browser.contexts
            probe = await VideoInspectTool(workspace).invoke({"path": receipt["path"]}, ctx)
            assert probe["first_frame_decoded"] and probe["duration_ms"] > 0
            cut = await VideoEditTool(workspace).invoke({"output": "recording.mp4", "segments": [
                {"path": receipt["path"], "start_ms": 0, "end_ms": min(400, probe["duration_ms"])},
            ]}, ctx)
            assert cut["frame_count"] > 0
        finally:
            await recording.close()
            await browser.close()
