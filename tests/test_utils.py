"""

"""
import json
import uuid
from typing import Dict, Any, Optional
from unittest.mock import MagicMock, Mock


def create_test_request(
    method: str,
    params: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """TODO: add docstring."""
    return {
        "type": "req",
        "id": request_id or str(uuid.uuid4()),
        "method": method,
        "params": params or {}
    }


def create_test_response(
    ok: bool = True,
    data: Optional[Any] = None,
    error: Optional[str] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """TODO: add docstring."""
    response = {
        "type": "resp",
        "id": request_id or str(uuid.uuid4()),
        "ok": ok
    }
    if data is not None:
        response["data"] = data
    if error:
        response["error"] = error
    return response


def create_test_event(
    event_type: str,
    payload: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """TODO: add docstring."""
    return {
        "type": "event",
        "event": event_type,
        "payload": payload or {}
    }


def mock_websocket_connection():
    """TODO: add docstring."""
    ws = MagicMock()
    ws.send = MagicMock()
    ws.recv = MagicMock()
    ws.close = MagicMock()
    return ws


def assert_response_ok(response: Dict[str, Any], expected_data: Optional[Any] = None):
    """TODO: add docstring."""
    assert response.get("ok") is True, f": {response}"
    if expected_data is not None:
        assert response.get("data") == expected_data


def assert_response_error(response: Dict[str, Any], expected_error: Optional[str] = None):
    """TODO: add docstring."""
    assert response.get("ok") is False, f": {response}"
    if expected_error:
        assert expected_error in str(response.get("error", ""))


def load_test_config(config_name: str = "test") -> Dict[str, Any]:
    """TODO: add docstring."""
    # TODO: comment cleaned
    return {
        "test": {
            "api": {
                "api_key": "test-key",
                "model": "test-model"
            },
            "memory": {
                "enabled": False
            }
        }
    }.get(config_name, {})


class AsyncMock(Mock):
    """TODO: add docstring."""
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)

