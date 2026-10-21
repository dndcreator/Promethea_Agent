from __future__ import annotations

import socket
from unittest.mock import Mock

import start_gateway_service as startup


def test_port_availability_detects_existing_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        assert startup._port_is_available("127.0.0.1", port) is False


def test_wait_for_http_stops_when_managed_process_exits(monkeypatch):
    process = Mock()
    process.poll.return_value = 1
    process.returncode = 1
    logger = Mock()
    urlopen = Mock()
    monkeypatch.setattr(startup.urllib.request, "urlopen", urlopen)

    assert startup._wait_for_http(
        startup.UI_DEV_URL,
        timeout_s=1,
        logger=logger,
        process=process,
    ) is False
    urlopen.assert_not_called()
    logger.error.assert_called_once()


def test_browser_opens_only_after_gateway_and_ui_are_ready(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    logger = Mock()
    wait_for_gateway = Mock(return_value=True)
    wait_for_http = Mock(return_value=True)
    browser_open = Mock()
    monkeypatch.setattr(startup, "_wait_for_gateway", wait_for_gateway)
    monkeypatch.setattr(startup, "_wait_for_http", wait_for_http)
    monkeypatch.setattr(startup.webbrowser, "open", browser_open)

    startup._open_browser_when_ready(process, logger)

    assert wait_for_gateway.call_args.args[0] == f"{startup.GATEWAY_URL}/health"
    assert wait_for_http.call_args.args[0] == startup.UI_DEV_URL
    browser_open.assert_called_once_with(startup.UI_DEV_URL)
