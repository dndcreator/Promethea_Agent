# Channel Framework

Channels are communication boundaries around the existing Runtime, not alternative
Agent loops or tools. Provider credentials belong to deployment, while local
identities and Memory stay in their existing owners.

## Ownership

- `BaseChannel` is a live provider transport with start/stop, provider message parsing and send methods. `ChannelRegistry` stores those instances, discovered through existing extension manifests.
- `ChannelAdapter` is a transport-neutral projection: `normalize_identity`, `permission_check`, `build_session_key`, `ingest_message`, `emit_response`, `emit_stream_chunk`. Web and HTTP have defaults; running Webhook plugins can provide the same projection through `protocol_adapter()`, registered on first use without a provider-name branch. This registry does not validate public provider signatures or prove account ownership.
- `ChannelDeliveryRuntime` validates provider ingress through its plugin, persists a receipt, resolves an existing IdentityStore binding, derives an owner/robot/scope/sender session key and dispatches `GatewayServer.handle_http_request`. ConversationService and ActionService retain all cognition and execution.
- `DeliveryStore` owns only inbox/outbox records and per-part acknowledgements; it is not a copy of Task checkpoints. An OS lock enforces single-host, single-process consumption.

These registries have different ownership, not competing execution paths. There
is no new first-level service, Memory backend or tool protocol.

## Identity And Control

Bot Webhooks require provider authentication: QQ raw-body Ed25519, Telegram
Secret Token, Feishu encrypted/signed events, DingTalk's timestamp HMAC, or
WeCom's signed AES envelope. DingTalk's official HTTP signature does not cover
the body; trusted HTTPS ingress is mandatory. Generic ingress preserves provider
query parameters and plaintext/JSON acknowledgements, including WeCom's GET
verification; no provider-specific Agent entrypoint is introduced.
Private pairing requires a high-entropy, expiring code issued to an
authenticated local user and consumed by a verified external sender. Bindings
reuse IdentityStore, independent of Memory backend selection. Provider identity
alone never becomes a local `user_id`, and unbound messages never create users.

Group context requires a dedicated shared identity and sender allowlist; it must
not borrow a personally paired user. Sensitive effects use the original exact
chat confirmation handler. Channel control commands never call tools directly.

## Delivery And Recovery

Acknowledgement follows durable receipt. Duplicate provider IDs do not rerun the
model. Replies and completed part counts are saved independently of Agent work.
Only a successful provider response advances send progress. A crash during
execution/sending becomes `uncertain`, never a blind replay; queued work and
not-yet-started replies may resume. Explicit retry resends only known-rejected
persisted replies, with no Agent rerun. Cross-platform exactly-once is not claimed.

Secrets stay in operator-owned root environment settings, outside per-user model
configuration and public contracts. Public account/pairing/delivery contracts
generate TS SDK types; `client.channels` is transport-only. Legacy unverified
channel notifications are not broadcast to all logged-in users and do not bypass
the verified ingress. `CHANNEL_MESSAGE` is an observation, not an executable
command; ConversationService no longer subscribes to it to start an unverified
sender-owned turn. Config-reload events carry change metadata rather than raw
deployment settings. See [operations and limits](../channels/README.md).
