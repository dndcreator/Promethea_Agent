"""Bounded local media tools; no shell, device, or network inputs."""
import asyncio
from contextlib import contextmanager
from fractions import Fraction
import os
from pathlib import Path
import tempfile
from threading import Event
from time import monotonic

from agentkit.mcp.tool_result import ToolExecutionResult
from agentkit.mcp.visual_content import workspace_image_content
from agentkit.security.sandbox import get_sandbox_policy
from gateway.tools.schema import array, input_object, integer, text
from .workspace_tools import _resolve_identity, _safe_path_under_root


FORMATS = {".mp4": "mov", ".mov": "mov", ".mkv": "matroska", ".webm": "matroska"}
FPS = 25
MAX_DURATION = 120_000


class MediaDependencyError(RuntimeError):
    code = "VIDEO_DEPENDENCY_MISSING"


def _av():
    try:
        import av
    except ImportError as exc:
        raise MediaDependencyError('Install the optional media extra: pip install ".[media]".') from exc
    return av


def _deny_io(*_):
    raise PermissionError("Video files cannot open secondary inputs.")


@contextmanager
def _video(path):
    av = _av()
    kind = FORMATS.get(path.suffix.lower())
    if kind is None:
        raise ValueError("Supported video containers: MP4, MOV, WebM and MKV.")
    with path.open("rb") as source, av.open(source, format=kind, io_open=_deny_io,
                                              options={"enable_drefs": "0"} if kind == "mov" else {}) as container:
        if not container.streams.video:
            raise ValueError("The file has no video track.")
        stream = container.streams.video[0]
        if not (0 < stream.width <= 4096 and 0 < stream.height <= 2160):
            raise ValueError("Video resolution exceeds the supported limit.")
        stream.codec_context.thread_count = 2
        yield container, stream


def _duration_ms(container, stream):
    if stream.duration is not None:
        return round(stream.duration * stream.time_base * 1000)
    return round(container.duration / 1000) if container.duration is not None else None


def _frames(container, stream, start_ms=0):
    offset = stream.start_time or 0
    deadline = monotonic() + 45
    if start_ms:
        container.seek(offset + int(Fraction(start_ms, 1000) / stream.time_base), stream=stream, backward=True)
    for frame in container.decode(stream):
        if monotonic() >= deadline:
            raise TimeoutError("Video decoding exceeded the processing allowance.")
        if frame.width > 4096 or frame.height > 2160:
            raise ValueError("Video frame resolution exceeds the supported limit.")
        if frame.pts is not None:
            yield (frame.pts - offset) * stream.time_base * 1000, frame


class _MediaTool:
    side_effect_level = "read_only"
    domain = "media"

    def __init__(self, workspace_service):
        self.workspace_service = workspace_service

    def root(self, ctx):
        if not ctx or not ctx.user_id or not ctx.session_id:
            raise PermissionError("Media tools require an owned workspace.")
        user, workspace = _resolve_identity({}, ctx)
        return Path(self.workspace_service.resolve_workspace_handle(user_id=user, workspace_id=workspace).root_path)

    @staticmethod
    def path(root, name, *, write=False):
        relative = Path(name)
        if not relative.parts or relative.anchor or ".." in relative.parts or any(":" in part for part in relative.parts):
            raise ValueError("Expected a workspace-relative file path.")
        path = _safe_path_under_root(root, name)
        if not get_sandbox_policy().check_path(str(path), workspace_root=root, intent="write" if write else "read").allowed:
            raise PermissionError("Media path is outside the permitted workspace.")
        if not write:
            if not path.is_file():
                raise FileNotFoundError(name)
            if path.stat().st_size > 512 * 1024 * 1024:
                raise ValueError("Media input exceeds 512 MiB.")
        return path


class WorkspaceImageViewTool(_MediaTool):
    tool_id = name = "image.view"
    description = "View a workspace image or browser screenshot as visual input. Requires a vision-capable model."
    input_schema = input_object({"path": text()}, required=("path",))

    async def invoke(self, args, ctx=None):
        root = self.root(ctx)
        raw = Path(args["path"])
        # Screenshot tools return an absolute artifact path; accept it only under this owned root.
        name = raw.relative_to(root).as_posix() if raw.is_absolute() and raw.is_relative_to(root) else args["path"]
        path = self.path(root, name)

        def read():
            from PIL import Image
            with Image.open(path, formats=["PNG", "JPEG", "WEBP"]) as image:
                meta = {"path": name, "width": image.width, "height": image.height}
                return ToolExecutionResult(self.name, True, value=meta, content=workspace_image_content(image))

        return await asyncio.to_thread(read)


class VideoInspectTool(_MediaTool):
    tool_id = name = "video.inspect"
    description = "Inspect a workspace video: duration in milliseconds, dimensions, audio tracks, and whether the first frame decodes."
    input_schema = input_object({"path": text()}, required=("path",))

    async def invoke(self, args, ctx=None):
        path = self.path(self.root(ctx), args["path"])

        def inspect():
            with _video(path) as (container, stream):
                return {"path": args["path"], "duration_ms": _duration_ms(container, stream), "width": stream.width,
                        "height": stream.height, "audio_tracks": len(container.streams.audio),
                        "first_frame_decoded": next(container.decode(stream), None) is not None}

        return await asyncio.to_thread(inspect)


class VideoFrameTool(_MediaTool):
    tool_id = name = "video.frame"
    timeout_ms = 50_000
    description = "View a frame at a millisecond timestamp in a workspace video. Requires a vision-capable model."
    input_schema = input_object({"path": text(), "at_ms": integer(minimum=0, maximum=1_800_000)}, required=("path", "at_ms"))

    async def invoke(self, args, ctx=None):
        path = self.path(self.root(ctx), args["path"])

        def read():
            with _video(path) as (container, stream):
                for timestamp, frame in _frames(container, stream, args["at_ms"]):
                    if timestamp >= args["at_ms"]:
                        meta = {"path": args["path"], "frame_ms": round(timestamp)}
                        return ToolExecutionResult(self.name, True, value=meta, content=workspace_image_content(frame.to_image()))
                raise ValueError("No decodable frame at or after the requested timestamp.")

        return await asyncio.to_thread(read)


class VideoEditTool(_MediaTool):
    tool_id = name = "video.edit"
    timeout_ms = 100_000
    description = "Cut and join ordered workspace video segments into a new silent H.264 MP4. Times are milliseconds; end is exclusive. Does not overwrite files."
    side_effect_level = "workspace_write"
    input_schema = input_object({"output": text(), "segments": {**array(input_object({
        "path": text(), "start_ms": integer(minimum=0, maximum=1_800_000),
        "end_ms": integer(minimum=1, maximum=1_800_000),
    }, required=("path", "start_ms", "end_ms"))), "minItems": 1, "maxItems": 12}}, required=("output", "segments"))

    async def invoke(self, args, ctx=None):
        root = self.root(ctx)
        target = self.path(root, args["output"], write=True)
        if target.suffix.lower() != ".mp4" or not target.parent.is_dir() or target.exists():
            raise ValueError("Output must be a new .mp4 in an existing workspace directory.")
        parts = [(self.path(root, row["path"]), row["start_ms"], row["end_ms"]) for row in args["segments"]]
        if not 1 <= len(parts) <= 12 or any(not 0 <= start < end <= 1_800_000 for _, start, end in parts) or sum(end - start for _, start, end in parts) > MAX_DURATION:
            raise ValueError("Use 1-12 valid ranges totaling no more than 120 seconds.")
        cancelled = Event()
        try:
            frames = await asyncio.to_thread(_render, parts, target, cancelled)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {"path": target.relative_to(root).as_posix(), "duration_ms": frames * 1000 // FPS,
                "segments": args["segments"], "audio": False, "frame_count": frames}


def _render(parts, target, cancelled):
    from PIL import Image, ImageOps

    av = _av()
    count = 0
    deadline = monotonic() + 90
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".mp4", delete=False) as temp:
        staged = Path(temp.name)
    try:
        with av.open(str(staged), "w", format="mp4", options={"movflags": "+faststart"}) as output:
            track = output.add_stream("libx264", rate=FPS)
            track.width, track.height, track.pix_fmt = 1280, 720, "yuv420p"
            track.codec_context.thread_count = 2
            track.options = {"preset": "veryfast"}
            for path, start, end in parts:
                with _video(path) as (container, stream):
                    duration = _duration_ms(container, stream)
                    if duration is None or end > duration:
                        raise ValueError("Segment extends beyond the known source duration.")
                    frames = iter(_frames(container, stream, start))
                    upcoming = next(frames, None)
                    if upcoming is None or upcoming[0] >= end:
                        raise ValueError("No source frame in the requested segment.")
                    current = upcoming[1]
                    for timestamp in range(start, end, 1000 // FPS):
                        if cancelled.is_set():
                            raise InterruptedError("Video edit cancelled.")
                        if monotonic() >= deadline:
                            raise TimeoutError("Video editing exceeded the processing allowance.")
                        while upcoming is not None and upcoming[0] <= timestamp:
                            current = upcoming[1]
                            upcoming = next(frames, None)
                        scaled = ImageOps.contain(current.to_image(), (track.width, track.height))
                        canvas = Image.new("RGB", (track.width, track.height))
                        canvas.paste(scaled, ((track.width - scaled.width) // 2, (track.height - scaled.height) // 2))
                        frame = av.VideoFrame.from_image(canvas)
                        frame.pts, frame.time_base = count, Fraction(1, FPS)
                        for packet in track.encode(frame):
                            output.mux(packet)
                        count += 1
            for packet in track.encode():
                output.mux(packet)
        if cancelled.is_set():
            raise InterruptedError("Video edit cancelled.")
        os.link(staged, target)
        return count
    finally:
        staged.unlink(missing_ok=True)
