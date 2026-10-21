import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import Error

from computer import browser_runtime as runtime
from config import config


def test_browser_preparation_settings_follow_existing_env_mechanism(monkeypatch):
    from config import load_config

    monkeypatch.setenv("SYSTEM__BROWSER_AUTO_INSTALL", "false")
    monkeypatch.setenv("SYSTEM__BROWSER_CHANNEL", "chrome")
    monkeypatch.setenv("SYSTEM__BROWSER_INSTALL_TIMEOUT_S", "90")
    current = load_config()
    assert current.system.browser_auto_install is False
    assert current.system.browser_channel == "chrome"
    assert current.system.browser_install_timeout_s == 90


@pytest.fixture
def browser(monkeypatch, tmp_path):
    monkeypatch.setattr(config.system, "browser_channel", "")
    monkeypatch.setattr(config.system, "browser_auto_install", True)
    monkeypatch.setattr(config.system, "browser_install_retry_delay_s", 60)
    executable = tmp_path / "chromium.exe"
    chromium = SimpleNamespace(executable_path=str(executable), launch=AsyncMock(return_value=object()))
    return SimpleNamespace(chromium=chromium), executable


@pytest.mark.asyncio
async def test_matching_chromium_is_reused_without_a_download(browser, monkeypatch):
    playwright, executable = browser
    executable.touch()
    installer = AsyncMock()
    monkeypatch.setattr(runtime, "_install_chromium", installer)
    await runtime.launch_browser(playwright, headless=True, chromium_sandbox=True)
    playwright.chromium.launch.assert_awaited_once_with(executable_path=str(executable), headless=True, chromium_sandbox=True)
    installer.assert_not_awaited()


@pytest.mark.asyncio
async def test_installed_channel_is_detected_with_the_same_sandbox_options(browser, monkeypatch):
    playwright, _ = browser
    value = object()
    playwright.chromium.launch.side_effect = [Error("channel missing"), value]
    installer = AsyncMock()
    monkeypatch.setattr(runtime, "_install_chromium", installer)
    assert await runtime.launch_browser(playwright, headless=True, chromium_sandbox=True) is value
    assert [call.kwargs["channel"] for call in playwright.chromium.launch.await_args_list] == ["msedge", "chrome"]
    assert all(call.kwargs["chromium_sandbox"] is True for call in playwright.chromium.launch.await_args_list)
    installer.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_channel_is_not_silently_replaced(browser, monkeypatch):
    playwright, _ = browser
    playwright.chromium.launch.side_effect = Error("explicit channel unavailable")
    installer = AsyncMock()
    monkeypatch.setattr(runtime, "_install_chromium", installer)
    with pytest.raises(Error, match="explicit channel"):
        await runtime.launch_browser(playwright, channel="chrome-beta", chromium_sandbox=True)
    assert playwright.chromium.launch.await_count == 1
    installer.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_setup_downloads_once_and_waits_until_ready(browser, monkeypatch):
    playwright, executable = browser
    ready = False
    installing = asyncio.Event()
    complete = asyncio.Event()

    async def launch(**kwargs):
        if kwargs.get("channel"):
            raise Error("channel missing")
        assert ready
        return object()

    async def install(_):
        nonlocal ready
        executable.touch()
        installing.set()
        await complete.wait()
        ready = True

    playwright.chromium.launch.side_effect = launch
    installer = AsyncMock(side_effect=install)
    monkeypatch.setattr(runtime, "_install_chromium", installer)
    first = asyncio.create_task(runtime.launch_browser(playwright, chromium_sandbox=True))
    await installing.wait()
    second = asyncio.create_task(runtime.launch_browser(playwright, chromium_sandbox=True))
    await asyncio.sleep(0)
    assert not second.done()
    complete.set()
    await asyncio.gather(first, second)
    installer.assert_awaited_once()


@pytest.mark.asyncio
async def test_preparation_failure_is_cooled_down_and_can_retry(browser, monkeypatch):
    playwright, executable = browser
    playwright.chromium.launch.side_effect = Error("channel missing")
    installer = AsyncMock(side_effect=runtime.BrowserSetupError("network unavailable"))
    monkeypatch.setattr(runtime, "_install_chromium", installer)
    for _ in range(2):
        with pytest.raises(runtime.BrowserSetupError, match="network unavailable"):
            await runtime.launch_browser(playwright)
    assert installer.await_count == 1
    monkeypatch.setattr(config.system, "browser_install_retry_delay_s", 0)

    async def install(_):
        executable.touch()

    installer.side_effect = install
    playwright.chromium.launch.side_effect = lambda **kwargs: object() if "executable_path" in kwargs else (_ for _ in ()).throw(Error("channel missing"))
    await runtime.launch_browser(playwright)
    assert installer.await_count == 2


@pytest.mark.asyncio
async def test_disabled_auto_install_does_not_download(browser, monkeypatch):
    playwright, _ = browser
    monkeypatch.setattr(config.system, "browser_auto_install", False)
    playwright.chromium.launch.side_effect = Error("channel missing")
    installer = AsyncMock()
    monkeypatch.setattr(runtime, "_install_chromium", installer)
    with pytest.raises(runtime.BrowserSetupError, match="disabled"):
        await runtime.launch_browser(playwright)
    installer.assert_not_awaited()


@pytest.mark.asyncio
async def test_installer_nonzero_exit_is_bounded_and_never_reports_ready(monkeypatch):
    process = SimpleNamespace(returncode=1, stdout=SimpleNamespace(read=AsyncMock(side_effect=[b"x" * 20_000, b""])), wait=AsyncMock(return_value=1))
    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(runtime.BrowserSetupError, match="exit 1") as error:
        await runtime._install_chromium(5)
    assert len(str(error.value)) < 3200


@pytest.mark.asyncio
async def test_stop_installer_only_terminates_its_own_process_tree(monkeypatch):
    children = [SimpleNamespace(kill=Mock()), SimpleNamespace(kill=Mock())]
    parent = SimpleNamespace(children=Mock(return_value=children))
    monkeypatch.setattr(runtime.psutil, "Process", Mock(return_value=parent))
    process = SimpleNamespace(pid=123, returncode=None, kill=Mock(), wait=AsyncMock())
    await runtime._stop_installer(process)
    runtime.psutil.Process.assert_called_once_with(123)
    parent.children.assert_called_once_with(recursive=True)
    assert all(child.kill.call_count == 1 for child in children)
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_installer_timeout_or_cancel_stops_the_process_tree(monkeypatch, cancel):
    started = asyncio.Event()

    async def wait():
        started.set()
        await asyncio.sleep(60)

    process = SimpleNamespace(pid=123, returncode=None, stdout=SimpleNamespace(read=AsyncMock(return_value=b"")), wait=wait)
    spawn = AsyncMock(return_value=process)
    stop = AsyncMock()
    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(runtime, "_stop_installer", stop)
    task = asyncio.create_task(runtime._install_chromium(0.01 if not cancel else 60))
    await started.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else runtime.BrowserSetupError):
        await task
    stop.assert_awaited_once_with(process)
    assert spawn.call_args.args[1:] == ("-m", "playwright", "install", "chromium")


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")
async def test_real_automatic_browser_launch_needs_no_channel_or_download(monkeypatch, tmp_path):
    from playwright.async_api import async_playwright

    monkeypatch.setattr(config.system, "browser_channel", "")
    monkeypatch.setattr(config.system, "browser_auto_install", False)
    async with async_playwright() as playwright:
        # A missing managed binary forces actual installed-browser detection.
        proxy = SimpleNamespace(chromium=SimpleNamespace(executable_path=str(tmp_path / "missing.exe"), launch=playwright.chromium.launch))
        browser = await runtime.launch_browser(proxy, headless=True, chromium_sandbox=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.set_content('<button onclick="this.textContent=2+3">Calculate</button>')
            await page.click("button")
            assert await page.locator("button").inner_text() == "5"
        finally:
            await browser.close()
