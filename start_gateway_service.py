"""Startup script for gateway-first service plus the Vite Web UI."""

import os
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from config import config
from utils.logger import setup_logger


ROOT_DIR = Path(__file__).resolve().parent
UI_DIR = ROOT_DIR / "UI"
GATEWAY_HOST = "127.0.0.1"
UI_HOST = "127.0.0.1"
GATEWAY_PORT = 8000
UI_PORT = 5173
GATEWAY_URL = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}"
UI_DEV_URL = f"http://{UI_HOST}:{UI_PORT}"


def _port_is_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
        return True
    except OSError:
        return False


def _select_port(host: str, default: int, env_name: str, logger) -> int:
    configured = str(os.environ.get(env_name, "") or "").strip()
    if configured:
        try:
            port = int(configured)
        except ValueError as exc:
            raise RuntimeError(f"{env_name} must be an integer") from exc
        if not 1 <= port <= 65535:
            raise RuntimeError(f"{env_name} must be between 1 and 65535")
        if not _port_is_available(host, port):
            raise RuntimeError(f"Configured port {port} from {env_name} is already in use")
        return port

    if _port_is_available(host, default):
        return default
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        selected = int(probe.getsockname()[1])
    logger.warning(f"Default port {default} is in use; selected {selected}")
    return selected


def _configure_runtime_endpoints(logger) -> None:
    global GATEWAY_PORT, UI_PORT, GATEWAY_URL, UI_DEV_URL
    GATEWAY_PORT = _select_port(GATEWAY_HOST, 8000, "PROMETHEA_GATEWAY_PORT", logger)
    UI_PORT = _select_port(UI_HOST, 5173, "PROMETHEA_UI_PORT", logger)
    GATEWAY_URL = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}"
    UI_DEV_URL = f"http://{UI_HOST}:{UI_PORT}"


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

    if not _port_is_available(UI_HOST, UI_PORT):
        logger.error(
            f"Web UI port {UI_PORT} became unavailable before startup. Restart Promethea."
        )
        return None

    command = [
        npm,
        "run",
        "dev",
        "--",
        "--host",
        UI_HOST,
        "--port",
        str(UI_PORT),
        "--strictPort",
    ]
    logger.info(f"Starting Web UI: {' '.join(command)}")
    try:
        child_env = os.environ.copy()
        child_env["PROMETHEA_GATEWAY_URL"] = GATEWAY_URL
        return subprocess.Popen(command, cwd=UI_DIR, env=child_env)
    except Exception as exc:
        logger.error(f"Failed to start Web UI dev server: {exc}")
        return None


def _wait_for_http(
    url: str,
    timeout_s: float,
    logger,
    *,
    process: subprocess.Popen | None = None,
) -> bool:
    deadline = time.monotonic() + timeout_s
    last_error = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            logger.error(f"Process exited before {url} became ready (exit={process.returncode})")
            return False
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return True
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    logger.warning(f"Timed out waiting for {url}: {last_error}")
    return False


def _open_browser_when_ready(ui_process: subprocess.Popen | None, logger) -> None:
    health_url = f"{GATEWAY_URL}/health"
    if not _wait_for_gateway(health_url, timeout_s=180, logger=logger):
        logger.error("Gateway did not become ready; browser was not opened")
        return

    if ui_process is None:
        logger.info(f"Gateway ready at {GATEWAY_URL}; Web UI is not running")
        return
    if not _wait_for_http(UI_DEV_URL, timeout_s=10, logger=logger, process=ui_process):
        logger.error("Gateway is ready, but Web UI is unavailable; browser was not opened")
        return

    logger.info(f"Promethea is ready: {UI_DEV_URL}")
    try:
        webbrowser.open(UI_DEV_URL)
        logger.info("Browser opened")
    except Exception as exc:
        logger.warning(f"Failed to open browser automatically: {exc}")


def _wait_for_gateway(url: str, timeout_s: float, logger) -> bool:
    deadline = time.monotonic() + timeout_s
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                payload = json.load(response)
            if (
                isinstance(payload, dict)
                and payload.get("gateway_ready") is True
                and payload.get("agent_ready") is True
                and payload.get("startup_status") in {"healthy", "degraded"}
            ):
                return True
            last_error = RuntimeError("health response did not identify a ready Promethea Gateway")
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
    logger = setup_logger(
        log_dir=str(config.system.log_dir),
        level=config.system.log_level,
        include_model_payloads=config.system.log_model_payloads,
    )
    ui_process = None

    try:
        _configure_runtime_endpoints(logger)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Promethea - Gateway Service")
    logger.info("=" * 60)
    logger.info(f"Gateway API : {GATEWAY_URL}")
    logger.info(f"Web UI      : {UI_DEV_URL}")

    try:
        ui_process = _start_ui_dev_server(logger)
        if ui_process and not _wait_for_http(
            UI_DEV_URL,
            timeout_s=60,
            logger=logger,
            process=ui_process,
        ):
            logger.error("Web UI failed to start; Gateway will continue without opening a browser")
            _stop_process(ui_process, logger)
            ui_process = None
        elif ui_process:
            logger.info("Web UI prepared; waiting for Gateway readiness")
    except Exception as e:
        logger.warning(f"Failed to prepare Web UI: {e}")
        ui_process = None

    try:
        import gateway.app  # noqa: F401
    except Exception as e:
        logger.error(f"Cannot import gateway app: {e}")
        import traceback

        logger.error(traceback.format_exc())
        logger.error("Please install dependencies first: pip install -e .")
        _stop_process(ui_process, logger)
        sys.exit(1)

    readiness_thread = threading.Thread(
        target=_open_browser_when_ready,
        args=(ui_process, logger),
        name="promethea-readiness",
        daemon=True,
    )
    readiness_thread.start()

    try:
        uvicorn.run(
            "gateway.app:app",
            host="0.0.0.0",
            port=GATEWAY_PORT,
            reload=False,
            log_level="info",
        )
    finally:
        _stop_process(ui_process, logger)
