"""Signed provider ingress and authenticated, owner-scoped channel controls."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from gateway.public_contracts import ChannelPairingRequest, ChannelPairing, ChannelAccount, ChannelDelivery
from channels.webhook_channel import WebhookChannel
from ..dispatcher import get_gateway_server
from .auth import get_current_user_id, user_manager


router = APIRouter(prefix="/channels", tags=["channels"])


def runtime():
    delivery = getattr(get_gateway_server(), "channel_delivery", None)
    if delivery is None:
        raise HTTPException(503, "Channel Runtime is not initialized")
    return delivery


@router.post("/{channel}/webhook")
async def webhook(channel: str, request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1_000_000:
            raise HTTPException(413, "Webhook payload exceeds limit")
    try:
        ack = await runtime().receive(channel, request.headers, bytes(body), request.query_params)
        return PlainTextResponse(ack) if isinstance(ack, str) else ack
    except PermissionError:
        raise HTTPException(403, "Webhook authentication or pairing failed") from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(400, "Invalid webhook payload") from None
    except (LookupError, OverflowError):
        raise HTTPException(503, "Channel unavailable or inbox full") from None


@router.get("/{channel}/webhook")
async def verify_webhook(channel: str, request: Request):
    service = runtime()
    if not service.running:
        raise HTTPException(503, "Channel delivery worker is not running")
    try:
        return PlainTextResponse(service.channel(channel).verify_webhook(request.query_params))
    except PermissionError:
        raise HTTPException(403, "Webhook authentication failed") from None
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, "Invalid verification request") from None
    except LookupError:
        raise HTTPException(503, "Channel unavailable") from None


@router.get("", response_model=list[ChannelAccount])
async def accounts(user_id: str = Depends(get_current_user_id)):
    service = runtime()
    bound = user_manager.identity_store.get_channels(user_id)
    rows = [{"channel": name, "account_id": channel.account_id, "running": service.running and channel.is_running and channel.is_connected,
             "bound": service.namespace(channel) in bound, "external_account_id": bound.get(service.namespace(channel))}
            for name, channel in service.server.channels.items() if isinstance(channel, WebhookChannel)]
    present = {f"{row['channel']}:{row['account_id']}" for row in rows}
    for namespace, external in bound.items():
        family, _, account = namespace.partition(":")
        if account and namespace not in present:
            rows.append({"channel": family, "account_id": account, "running": False, "bound": True, "external_account_id": external})
    return rows


@router.post("/pairings", response_model=ChannelPairing)
async def pairing(body: ChannelPairingRequest, user_id: str = Depends(get_current_user_id)):
    service = runtime()
    if not service.running:
        raise HTTPException(503, "Channel delivery worker is not running")
    try:
        channel = service.channel(body.channel)
    except LookupError:
        raise HTTPException(503, "Channel is not running") from None
    if user_manager.identity_store.get_by_id(user_id) is None:
        raise HTTPException(404, "Account not found")
    result = user_manager.identity_store.issue_channel_pairing(user_id, service.namespace(channel))
    return {"channel": body.channel, **result}


@router.delete("/{channel}/binding")
async def unbind(channel: str, user_id: str = Depends(get_current_user_id)):
    store = user_manager.identity_store
    for namespace in store.get_channels(user_id):
        if namespace == channel or namespace.startswith(channel + ":"):
            store.unbind_channel(user_id, namespace)
    return {"ok": True}


@router.get("/deliveries", response_model=list[ChannelDelivery])
async def deliveries(user_id: str = Depends(get_current_user_id)):
    return runtime().store.list_user(user_id)


@router.post("/deliveries/{delivery_id}/retry")
async def retry_delivery(delivery_id: str, user_id: str = Depends(get_current_user_id)):
    service = runtime()
    row = service.store.get(delivery_id)
    if not row or row["user_id"] != user_id:
        raise HTTPException(404, "Delivery not found")
    if row["state"] != "delivery_failed":
        raise HTTPException(409, "Only a provider-rejected delivery can be retried; uncertain execution must be inspected")
    # Retry the persisted reply only. Never rerun the Agent or replay unknown effects.
    try:
        service._authorized(row, json.loads(row["envelope"]))
    except (PermissionError, LookupError):
        raise HTTPException(403, "Channel authority was revoked") from None
    service.store.update(delivery_id, "ready")
    service.wakeup.set()
    return {"ok": True}
