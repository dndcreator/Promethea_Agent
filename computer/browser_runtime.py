"""Shared browser preparation, not a tool or an Agent control loop."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import weakref

import psutil

logger = logging.getLogger(__name__)
_locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_failures: dict[str, tuple[float, str]] = {}


class BrowserSetupError(RuntimeError):
    code = "BROWSER_SETUP_FAILED"


def setup_timeout() -> float:
    from config import config

    return float(config.system.browser_install_timeout_s) if config.system.browser_auto_install else 0


async def _stop_installer(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    for child in reversed(children):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        process.kill()
    except ProcessLookupError:
        pass
    await process.wait()


async def _install_chromium(timeout: float) -> None:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "playwright", "install", "chromium",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        creationflags=flags,
    )
    output = bytearray()

    async def drain() -> None:
        while chunk := await process.stdout.read(4096):
            output.extend(chunk)
            del output[:-8000]

    reader = asyncio.create_task(drain())
    try:
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise BrowserSetupError("Browser download timed out; check connectivity and retry.") from exc
        await reader
        if process.returncode:
            detail = output.decode("utf-8", errors="replace")[-3000:]
            raise BrowserSetupError(f"Browser download failed (exit {process.returncode}): {detail}")
    finally:
        try:
            await _stop_installer(process)
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)


async def _ensure_chromium(executable: Path) -> None:
    from config import config

    loop = asyncio.get_running_loop()
    lock = _locks.setdefault(loop, asyncio.Lock())
    async with lock:
        if executable.is_file():
            return
        key = str(executable)
        previous = _failures.get(key)
        if previous and time.monotonic() - previous[0] < config.system.browser_install_retry_delay_s:
            raise BrowserSetupError(previous[1])
        logger.info("Preparing managed Chromium runtime")
        try:
            await _install_chromium(float(config.system.browser_install_timeout_s))
            if not executable.is_file():
                raise BrowserSetupError("Browser preparation finished without the expected executable.")
        except (BrowserSetupError, OSError) as exc:
            _failures[key] = (time.monotonic(), str(exc))
            raise BrowserSetupError(str(exc)) from exc
        _failures.pop(key, None)
        logger.info("Managed Chromium runtime is ready")


async def launch_browser(playwright: Any, *, channel: str = "", **options: Any) -> Any:
    from config import config
    from playwright.async_api import Error

    requested = str(channel or config.system.browser_channel or "").strip()
    if requested:
        # An explicit administrator/user selection must not silently change.
        return await playwright.chromium.launch(channel=requested, **options)
    installing = _locks.get(asyncio.get_running_loop())
    if installing is not None and installing.locked():
        async with installing:
            pass
    executable = Path(playwright.chromium.executable_path)
    managed_error = None
    if executable.is_file():
        try:
            # Use the matching full build for both headed and headless consumers.
            return await playwright.chromium.launch(executable_path=str(executable), **options)
        except Error as exc:
            managed_error = exc
    unavailable = []
    for candidate in ("msedge", "chrome"):
        try:
            browser = await playwright.chromium.launch(channel=candidate, **options)
            logger.info("Using installed browser channel: %s", candidate)
            return browser
        except Error as exc:
            unavailable.append(str(exc)[-500:])
    if not config.system.browser_auto_install:
        raise BrowserSetupError("No usable browser found and automatic preparation is disabled. " + " | ".join(unavailable))
    if managed_error is not None:
        raise BrowserSetupError("Installed browsers could not launch; check OS dependencies or browser policy. " + str(managed_error)[-1500:]) from managed_error
    await _ensure_chromium(executable)
    try:
        return await playwright.chromium.launch(executable_path=str(executable), **options)
    except Error as exc:
        raise BrowserSetupError(
            "Chromium is installed but cannot launch. Check OS dependencies or browser policy; "
            "the sandbox was not weakened. " + str(exc)[-1500:]
        ) from exc
