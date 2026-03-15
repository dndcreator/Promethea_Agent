# Playbook: How to Add a Channel

This guide explains how to add a new input channel (e.g. Slack, Discord, WeChat, SMS) to Promethea without modifying the core pipeline.

---

## Concepts

A **channel** is any source of user messages. The channel adapter framework (`channels/`) normalizes every channel's input/output to the same `GatewayRequest` / `GatewayResponse` contract.

The core pipeline never sees raw Slack messages or Telegram payloads — it only sees normalized `GatewayRequest` objects.

---

## Step 1 — Create the adapter file

```bash
touch channels/adapters/slack_adapter.py
```

### Minimal implementation

```python
from __future__ import annotations

from typing import Any, Dict, Optional

from channels.base import ChannelAdapter, ChannelMetadata, NormalizedMessage


class SlackAdapter(ChannelAdapter):
    channel_id = "slack"
    display_name = "Slack"

    def normalize_identity(self, raw: Dict[str, Any]) -> Dict[str, str]:
        """Extract user_id and session_id from the Slack event payload."""
        return {
            "user_id": raw["event"]["user"],
            "session_id": f"slack_{raw['event']['channel']}",
        }

    def ingest_message(self, raw: Dict[str, Any]) -> NormalizedMessage:
        identity = self.normalize_identity(raw)
        return NormalizedMessage(
            content=raw["event"]["text"],
            user_id=identity["user_id"],
            session_id=identity["session_id"],
            channel_id=self.channel_id,
            raw=raw,
        )

    def permission_check(self, identity: Dict[str, str], raw: Dict[str, Any]) -> bool:
        # Return False to block the message (e.g. banned users)
        return True

    def emit_response(self, session_id: str, text: str, metadata: Optional[Dict] = None) -> None:
        # Post to Slack using slack_sdk or requests
        ...

    def emit_stream_chunk(self, session_id: str, chunk: str) -> None:
        # Most IM channels do not support streaming — just buffer and send when done
        ...
```

---

## Step 2 — Register the adapter

Open `channels/adapters/__init__.py` (or `channels/adapter_registry.py`) and register:

```python
from channels.adapters.slack_adapter import SlackAdapter

def get_default_adapters():
    return [
        WebAdapter(),
        HttpApiAdapter(),
        TelegramAdapter(),
        SlackAdapter(),   # ← add this
    ]
```

---

## Step 3 — Add the inbound route

Create or modify the HTTP route that receives Slack events:

```python
# gateway/http/routes/slack.py

from fastapi import APIRouter, Request
from channels.adapter_registry import get_adapter

router = APIRouter(prefix="/channels/slack")

@router.post("/events")
async def slack_events(request: Request):
    raw = await request.json()
    adapter = get_adapter("slack")
    message = adapter.ingest_message(raw)
    if not adapter.permission_check(message.identity, raw):
        return {"ok": False, "reason": "forbidden"}

    # Forward to gateway
    from gateway.server import handle_channel_message
    response = await handle_channel_message(message)
    adapter.emit_response(message.session_id, response.text)
    return {"ok": True}
```

Register the router in `gateway/http/router.py`:

```python
from gateway.http.routes.slack import router as slack_router
app.include_router(slack_router)
```

---

## Step 4 — Handle the outbound response

Promethea calls `adapter.emit_response(session_id, text)` after each turn.  
Implement this to send the reply back to Slack:

```python
from slack_sdk import WebClient

client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

def emit_response(self, session_id: str, text: str, metadata=None):
    channel_id = session_id.replace("slack_", "")
    client.chat_postMessage(channel=channel_id, text=text)
```

---

## Step 5 — Add tests

```python
# tests/test_slack_adapter.py

from channels.adapters.slack_adapter import SlackAdapter

def test_ingest_message():
    adapter = SlackAdapter()
    raw = {"event": {"user": "U123", "channel": "C456", "text": "Hello"}}
    msg = adapter.ingest_message(raw)
    assert msg.user_id == "U123"
    assert msg.session_id == "slack_C456"
    assert msg.content == "Hello"
    assert msg.channel_id == "slack"
```

---

## Checklist

- [ ] Adapter file created in `channels/adapters/`
- [ ] `channel_id` is unique and lowercase
- [ ] `normalize_identity` returns `user_id` and `session_id`
- [ ] `ingest_message` produces a `NormalizedMessage`
- [ ] `emit_response` delivers the reply
- [ ] Adapter registered in `adapter_registry.py`
- [ ] HTTP route created and registered
- [ ] Tests added for normalize_identity and ingest_message
- [ ] PR description answers the six PR checklist questions

---

## What you do NOT need to change

- `gateway/conversation_pipeline.py`
- `gateway/memory_service.py`
- `gateway/tool_service.py`
- `gateway/protocol.py`
- Any memory backend

The channel adapter is a normalization boundary. The core runtime is channel-agnostic.
