"""Capture one isolated browser tab, never the user's desktop or normal tabs."""
import asyncio
from contextlib import suppress
import logging
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from .browser_observation import snapshot

logger = logging.getLogger(__name__)


class BrowserRecording:
    def __init__(self, browser, workspace: Path, sandbox):
        self.browser, self.workspace, self.sandbox = browser, workspace, sandbox
        self.context = self.page = self.timer = None
        self.started = 0.0
        self.receipt = None
        self.lock = asyncio.Lock()

    @property
    def active(self):
        return self.context is not None

    def elapsed(self):
        return round((monotonic() - self.started) * 1000)

    async def _route(self, route):
        url = route.request.url
        if urlsplit(url).scheme in {"https", "http"} and self.sandbox.check_url(url).allowed:
            await route.continue_()
        else:
            await route.abort()

    async def _expire(self, seconds):
        await asyncio.sleep(seconds)
        try:
            await self.close()
        except Exception:
            logger.exception("Browser recording could not be finalized")

    async def _stop(self):
        if self.timer is not None and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.timer = None
        if not self.active:
            return self.receipt
        video = self.page.video if self.page is not None else None
        duration = self.elapsed()
        try:
            await self.context.close()
            if video is not None:
                path = Path(await video.path()).resolve()
                if not path.is_relative_to(self.workspace) or not path.is_file():
                    raise RuntimeError("Browser did not finalize a workspace recording.")
                self.receipt = {"path": path.relative_to(self.workspace).as_posix(), "capture_elapsed_ms": duration}
            return self.receipt
        finally:
            self.context = self.page = None

    async def close(self):
        async with self.lock:
            return await self._stop()

    async def execute(self, action, params):
        async with self.lock:
            return await self._execute(action, params)

    async def _execute(self, action, params):
        timeout = min(20_000, max(1, int(params.get("timeout", 10_000))))
        if action == "record_start":
            if self.active:
                raise ValueError("Stop the active recording before starting another.")
            url = str(params.get("url") or "").strip()
            parsed = urlsplit(url)
            if parsed.scheme not in {"https", "http"} or parsed.username is not None or not self.sandbox.check_url(url).allowed:
                raise PermissionError("Recording requires an allowed public browser URL.")
            limit = int(params.get("duration_s", 300))
            if not 10 <= limit <= 600:
                raise ValueError("Recording limit must be between 10 and 600 seconds.")
            directory = self.workspace / "recordings" / uuid4().hex
            if directory.resolve() != directory or not self.sandbox.check_path(
                str(directory), intent="write", workspace_root=self.workspace,
            ).allowed:
                raise PermissionError("Workspace recordings directory is not writable.")
            self.receipt = None
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 720}, record_video_dir=directory,
                record_video_size={"width": 1280, "height": 720}, service_workers="block", accept_downloads=False,
            )
            try:
                await self.context.route("**/*", self._route)
                if hasattr(self.context, "route_web_socket"):
                    await self.context.route_web_socket("**/*", lambda socket: socket.close())
                self.started = monotonic()
                self.page = await self.context.new_page()
                self.page.on("popup", lambda page: page.close())
                await self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                self.timer = asyncio.create_task(self._expire(max(0, limit - self.elapsed() / 1000)))
            except BaseException:
                with suppress(Exception):
                    await self._stop()
                raise
            return {"recording": True, "url": self.page.url, "elapsed_ms": self.elapsed(), "limit_s": limit}
        if action == "record_stop":
            receipt = await self._stop()
            if receipt is None:
                raise ValueError("No finalized recording is available.")
            return receipt
        if self.page is None or self.page.is_closed():
            raise ValueError("No active recording tab. Use browser_action(action='record_start', url=...) before record_* interactions. Ordinary goto does not start recording.")
        at = self.elapsed()
        if action == "record_snapshot":
            state = await snapshot(self.page, max_nodes=params.get("max_nodes", 40), include_state=True)
        elif action == "record_screenshot":
            import base64
            image = await self.page.screenshot(timeout=timeout, animations="disabled")
            state = {"screenshot": base64.b64encode(image).decode("ascii")}
        elif action == "record_press":
            keys = params.get("keys") or [params.get("key")]
            if not isinstance(keys, list) or not 1 <= len(keys) <= 32 or any(not isinstance(key, str) or not key for key in keys):
                raise ValueError("Provide 1-32 explicit keys.")
            await asyncio.wait_for(self._press(keys), timeout / 1000)
            state = {"key_count": len(keys)}
        elif action == "record_click":
            await self.page.locator(params["selector"]).click(timeout=timeout)
            state = {"selector": params["selector"]}
        else:
            raise ValueError("Unknown recording action.")
        return {**state, "url": self.page.url, "start_ms": at, "end_ms": self.elapsed()}

    async def _press(self, keys):
        for key in keys:
            await self.page.keyboard.press(key)
            await asyncio.sleep(0.12)
