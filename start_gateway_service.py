"""Startup script for gateway-first service plus the Vite Web UI."""

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from utils.logger import setup_logger


ROOT_DIR = Path(__file__).resolve().parent
UI_DIR = ROOT_DIR / "UI"
GATEWAY_URL = "http://127.0.0.1:8000"
UI_DEV_URL = "http://127.0.0.1:5173"


def _npm_command() -> str | None:
    found = shutil.which("npm.cmd") or shutil.which("npm")
    if found:
        return found

    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "nodejs" / "npm.cmd",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "nodejs" / "npm.cmd",
        Path(os.environ.get("APPDATA", "")) / "npm" / "npm.cmd",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _run_ui_install(npm: str, logger) -> bool:
    package_json = UI_DIR / "package.json"
    package_lock = UI_DIR / "package-lock.json"
    node_modules = UI_DIR / "node_modules"
    if not package_json.exists():
        logger.warning("Vite UI package.json not found, skipping UI dev server")
        return False
    if node_modules.exists():
        return True

    command = [npm, "ci"] if package_lock.exists() else [npm, "install"]
    logger.info(f"UI dependencies are missing, running: {' '.join(command)}")
    try:
        subprocess.run(command, cwd=UI_DIR, check=True)
    except Exception as exc:
        logger.error(f"Failed to install UI dependencies: {exc}")
        logger.error("You can run manually: cd UI && npm ci")
        return False
    return True


def _start_ui_dev_server(logger) -> subprocess.Popen | None:
    if os.environ.get("PROMETHEA_SKIP_UI", "").lower() in {"1", "true", "yes"}:
        logger.info("PROMETHEA_SKIP_UI is set, skipping Web UI dev server")
        return None

    npm = _npm_command()
    if not npm:
        logger.warning("npm was not found in PATH, skipping Web UI dev server")
        logger.warning("Install Node.js, reopen PowerShell, then run: cd UI && npm ci && npm run dev")
        return None

    if not _run_ui_install(npm, logger):
        return None

    command = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"]
    logger.info(f"Starting Web UI: {' '.join(command)}")
    try:
        return subprocess.Popen(command, cwd=UI_DIR)
    except Exception as exc:
        logger.error(f"Failed to start Web UI dev server: {exc}")
        return None


def _wait_for_http(url: str, timeout_s: float, logger) -> bool:
    deadline = time.monotonic() + timeout_s
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return True
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    logger.warning(f"Timed out waiting for {url}: {last_error}")
    return False


def _stop_process(process: subprocess.Popen | None, logger) -> None:
    if not process or process.poll() is not None:
        return
    logger.info("Stopping Web UI dev server")
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


if __name__ == "__main__":
    logger = setup_logger()
    ui_process = None

    logger.info("=" * 60)
    logger.info("Promethea - Gateway Service")
    logger.info("=" * 60)
    logger.info(f"Gateway API : {GATEWAY_URL}")
    logger.info(f"Web UI      : {UI_DEV_URL}")

    try:
        ui_process = _start_ui_dev_server(logger)
        if ui_process:
            _wait_for_http(UI_DEV_URL, timeout_s=12, logger=logger)
        webbrowser.open(UI_DEV_URL if ui_process else GATEWAY_URL)
        logger.info("Browser opened")
    except Exception as e:
        logger.warning(f"Failed to open browser automatically: {e}")

    try:
        import gateway.app  # noqa: F401
    except Exception as e:
        logger.error(f"Cannot import gateway app: {e}")
        import traceback

        logger.error(traceback.format_exc())
        logger.error("Please install dependencies first: pip install -e .")
        _stop_process(ui_process, logger)
        sys.exit(1)

    try:
        uvicorn.run(
            "gateway.app:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            log_level="info",
        )
    finally:
        _stop_process(ui_process, logger)
