# Channels Module

`channels` integrates different message sources and normalizes them into a unified internal format.

## Key Files

- `channels/base.py`: base channel abstraction
- `channels/registry.py`: channel registry
- `channels/router.py`: message routing
- `channels/web_channel.py`: web channel
- `channels/wecom_channel.py`: WeCom channel
- `channels/feishu_channel.py`: Feishu channel
- `channels/dingtalk_channel.py`: DingTalk channel

## Workflow

1. Channel receives inbound message.
2. It normalizes payload shape.
3. It delegates to gateway/conversation processing.
4. It sends the response back through the same channel.

## Notes

- Keep the channel layer adapter-only.
- Centralize auth and user mapping in upper layers.
- Get basic send/receive stable before adding advanced features.

## Implemented Bot Ingress

QQ official and Telegram transports are ordinary `extensions/qq` and
`extensions/telegram` plugins. Their channel files own provider authentication,
normalization and HTTP text sends. `delivery_runtime.py` resolves verified
IdentityStore bindings and calls `GatewayServer.handle_http_request`; it contains
no Agent, Prompt, Memory or tool-policy decisions. `delivery_store.py` owns durable
receipts/replies and conservative crash recovery; `runtime_lock.py` owns the
single-host worker lock. Adapter registry holds protocol projections; channel
registry holds live transports, not competing Agent execution systems.

Status means local readiness, not verified platform delivery. Legacy enterprise
callbacks are not silently treated as authenticated Agent input.
See [deployment and acceptance](../docs/channels/README.md).
