from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict


class HttpConnection:
    """Minimal connection shim for HTTP->gateway handler reuse."""

    def __init__(self, uid: str):
        self.connection_id = f"http_{uuid.uuid4().hex}"
        self.identity = SimpleNamespace(device_id=uid)
        self.is_authenticated = True
        self.metadata: Dict[str, Any] = {"transport": "http"}

    async def send_event(self, *args, **kwargs):
        _ = (args, kwargs)
        return None

    async def send_message(self, *args, **kwargs):
        _ = (args, kwargs)
        return None

    async def send_response(self, *args, **kwargs):
        _ = (args, kwargs)
        return None
