"""Authenticated provider delivery around the existing Gateway execution entrypoint."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time

from loguru import logger

from gateway.protocol import RequestType
from .delivery_store import DeliveryStore
from .runtime_lock import RuntimeLock
from .webhook_channel import ProviderRejected, WebhookChannel


def digest(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


class ChannelDeliveryRuntime:
    def __init__(self, *, server, identities, settings, path):
        self.server, self.identities, self.settings = server, identities, settings
        self.store = DeliveryStore(path, queue_limit=settings.queue_limit, retention_days=settings.retention_days)
        self.lock = RuntimeLock(str(path) + ".lock")
        self.worker = None
        self.wakeup = asyncio.Event()

    @property
    def running(self):
        return self.worker is not None and not self.worker.done()

    def channel(self, name):
        channel = self.server.channels.get(name)
        if not isinstance(channel, WebhookChannel) or not channel.is_running or not channel.is_connected:
            raise LookupError("channel is not enabled and running")
        adapters = getattr(self.server, "channel_adapter_registry", None)
        if adapters is not None and adapters.get(name) is None:
            adapters.register(channel.protocol_adapter())
        return channel

    def namespace(self, channel):
        return f"{channel.channel_name}:{channel.account_id}"

    def owner(self, channel, envelope):
        if envelope["scope"] == "group":
            group = channel.settings.groups.get(envelope["receiver_id"])
            if not group or envelope["sender_id"] not in group.allowed_senders:
                return None
            user = self.identities.get_by_id(group.user_id)
            # A shared group must not borrow a personally paired identity.
            if user and self.identities.get_channels(user["user_id"]):
                return None
            return user
        return self.identities.get_by_channel(self.namespace(channel), envelope["sender_id"])

    async def receive(self, name, headers, body, query=None):
        if not self.running:
            raise LookupError("channel delivery worker is not running")
        channel = self.channel(name)
        ack, event = channel.accept_request(headers, body, query or {})
        if event is None:
            return ack
        event = {key: event[key] for key in ("message_id", "sender_id", "receiver_id", "scope", "content", "reply_to")}
        if any(not isinstance(value, str) or not value.strip() for value in event.values()) or event["scope"] not in {"private", "group"}:
            raise ValueError("invalid normalized channel message")
        if len(event["content"]) > 16000 or any(len(event[key]) > 256 for key in ("message_id", "sender_id", "receiver_id", "reply_to")):
            raise ValueError("channel message exceeds limits")
        identity = digest(name, channel.account_id, event["scope"], event["sender_id"], event["receiver_id"], event["message_id"])
        if self.store.get(identity):
            return ack
        self.store.ensure_capacity()
        response = None
        user = self.owner(channel, event)
        if event["scope"] != "private" and event["content"].startswith("/bind "):
            return ack
        if event["scope"] == "private" and event["content"].startswith("/bind "):
            token = event["content"][6:].strip()
            target = self.identities.consume_channel_pairing(token, self.namespace(channel), event["sender_id"])
            if not target:
                raise PermissionError("invalid or expired pairing code")
            user = self.identities.get_by_id(target)
            response = {"content": "[Runtime] 已绑定 / Account linked.", "kind": "transport_notice"}
            event["content"] = ""  # Never persist pairing tokens in transcripts or transport data.
        if not user:
            logger.info("Ignored unbound/unauthorized {} sender={} scope={}", name, event["sender_id"], event["scope"])
            return ack
        # Hash the local owner into the key: rebinding cannot reopen another owner's session.
        session = f"{name}_" + digest(channel.account_id, user["user_id"], event["scope"], event["receiver_id"], event["sender_id"])[:40]
        event.update(account_id=channel.account_id, accepted_at=time.time())
        self.store.enqueue(identity, name, user["user_id"], session, event, response=response)
        self.wakeup.set()
        return ack  # Durable receipt precedes provider acknowledgement.

    def start(self):
        if self.worker and not self.worker.done():
            return
        self.lock.acquire()
        try:
            self.store.recover()
            self.worker = asyncio.create_task(self._work(), name="channel-delivery")
        except BaseException:
            self.lock.close()
            raise

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
        self.lock.close()

    def _authorized(self, row, event):
        channel = self.channel(row["channel"])
        user = self.owner(channel, event)
        if channel.account_id != event["account_id"] or not user or user["user_id"] != row["user_id"]:
            raise PermissionError("channel binding has been revoked")
        return channel

    async def _work(self):
        while True:
            self.wakeup.clear()
            row = self.store.claim()
            if row is None:
                await self.wakeup.wait()
                continue
            try:
                event = json.loads(row["envelope"])
                channel = self._authorized(row, event)
                if row["state"] == "processing":
                    response = await self._run(row, event)
                    self.store.update(row["delivery_id"], "ready", response=response)
                    self.wakeup.set()
                else:
                    await self._deliver(channel, row, event)
            except asyncio.CancelledError:
                self.store.update(row["delivery_id"], "uncertain", error_code="RUNTIME_INTERRUPTED")
                raise
            except (PermissionError, LookupError):
                self.store.update(row["delivery_id"], "revoked", error_code="CHANNEL_AUTHORITY_REVOKED")
            except ProviderRejected as exc:
                self.store.update(row["delivery_id"], "delivery_failed", error_code=exc.code)
            except Exception:
                # Do not persist/log provider exception strings: URLs can contain tokens.
                self.store.update(row["delivery_id"], "uncertain", error_code="TRANSPORT_OR_RUNTIME_UNCERTAIN")
                logger.warning("Channel delivery {} stopped with an uncertain outcome", row["delivery_id"])

    async def _run(self, row, event):
        content = event["content"]
        params = {"channel": row["channel"], "session_id": row["session_id"], "message": content, "metadata": {"channel_message_id": event["message_id"], "channel_scope": event["scope"], "delivery_id": row["delivery_id"]}}
        method = RequestType.CHAT
        if content.startswith(("/approve ", "/reject ")):
            if event["scope"] != "private":
                return {"content": "[Runtime] 请在 Promethea 中审批 / Approve in Promethea.", "kind": "transport_notice"}
            action, tool_id = content.split(maxsplit=1)
            params.update(action=action[1:], tool_call_id=tool_id.strip())
            method = RequestType.CHAT_CONFIRM
        elif self.server.message_manager.get_pending_confirmation(row["session_id"], user_id=row["user_id"]):
            return {"content": "[Runtime] 当前会话有待审批操作 / This conversation has a pending approval.", "kind": "transport_notice"}
        response = await self.server.handle_http_request(method=method, params=params, user_id=row["user_id"], retries=0, timeout_ms=int(self.settings.turn_timeout_s * 1000), idempotency_key=f"channel:{row['delivery_id']}")
        if not response.ok:
            # A Runtime notice is explicitly not a fabricated Agent answer.
            return {"content": "[Runtime] 本次运行未完成，请在 Promethea 查看记录 / Run incomplete; inspect its record in Promethea.", "kind": "transport_notice", "execution_status": "failed"}
        payload = response.payload or {}
        if payload.get("status") == "needs_confirmation":
            pending = self.server.message_manager.get_pending_confirmation(row["session_id"], user_id=row["user_id"]) or {}
            if pending.get("confirmation_type") == "reasoning_outcome":
                return {"content": payload.get("response") or payload.get("response_text") or "", "kind": "agent", "execution_status": "waiting_confirmation"}
            tool_id = str(payload.get("tool_call_id") or "")
            return {"content": f"[Runtime] 等待审批 / Approval required: {payload.get('tool_name', '')}\n/approve {tool_id}\n/reject {tool_id}", "kind": "transport_notice", "execution_status": "waiting_confirmation"}
        text = payload.get("response_text") or payload.get("response") or ""
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("empty Agent reply")
        return {"content": text, "kind": "agent", "execution_status": "completed"}

    async def _deliver(self, channel, row, event):
        if channel.reply_window_s is not None and time.time() - event["accepted_at"] >= channel.reply_window_s:
            raise ProviderRejected("PASSIVE_REPLY_WINDOW_EXPIRED")
        response = json.loads(row["response"])
        text = response["content"]
        parts = [text[index:index + channel.settings.reply_chars] for index in range(0, len(text), channel.settings.reply_chars)]
        if len(parts) > channel.settings.max_reply_parts:
            raise ProviderRejected("REPLY_TOO_LONG_OPEN_CONVERSATION")
        for index in range(row["next_part"], len(parts)):
            self._authorized(row, event)
            result = await channel.send_text(event["receiver_id"], parts[index], scope=event["scope"], reply_to=event["reply_to"], sequence=index + 1)
            if result.get("success") is not True:
                raise RuntimeError("send outcome is not confirmed")
            self.store.update(row["delivery_id"], "delivering", next_part=index + 1)
        self.store.update(row["delivery_id"], "delivered")
