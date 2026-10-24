# Add A Channel

Use [QQ](../channels/qq.md), [Telegram](../channels/telegram.md) and
[enterprise platforms](../channels/enterprise.md) to deploy existing
plugins. This guide is for implementing another provider without changing Agent
Core. The old illustrative `NormalizedMessage` interface does not exist; use the
real contracts below.

## 1. Provider Transport

Implement `channels.base.BaseChannel`, or subclass
`channels.webhook_channel.WebhookChannel` for a signed HTTP bot. Existing working
references are `channels/qq_channel.py` and `channels/telegram_channel.py`.

For the shared webhook transport, implement:

```python
def accept_webhook(self, headers, body: bytes):
    # Verify the provider against the original bytes before accepting an event.
    # Return (provider_ack, None) for verified, unsupported events.
    ...

async def send_text(self, receiver_id, content, *, reply_to, sequence=1, **kwargs):
    # Return success only after the provider confirms a message ID.
    ...
```

For query-authenticated/XML providers, override
`accept_request(self, headers, body, query)` instead; `verify_webhook(self, query)`
handles an optional GET verification handshake. Acknowledgements may be a JSON
object or plaintext string; HTTP serialization remains at the existing route.
These hooks only verify/normalize transport data, never dispatch Agent work.
See `channels/wecom_channel.py`. Follow each provider's actual signature coverage;
do not describe a timestamp-only signature as raw-body authentication.

A supported inbound event returns these bounded fields, not a raw provider body:

```json
{
  "message_id": "provider-stable-id",
  "sender_id": "external-user-id",
  "receiver_id": "provider-chat-id",
  "scope": "private",
  "content": "message text",
  "reply_to": "original-provider-message-id"
}
```

Set a non-secret, stable `account_id` that namespaces provider identities. Add
typed operator settings in `channels/settings.py`, following root `.env` and
nested `CHANNELS__...` conventions. Keep credentials out of plugin JSON, status,
exceptions, public types and per-user model configuration. Use the provider's
actual freshness/replay rules and structured error codes. Never retry an unknown
outbound effect merely because an HTTP response was lost.

## 2. Existing Plugin Discovery

Create `extensions/<provider>/promethea.plugin.json` with `kind: "channel"` and a
`plugin.py`. Use `extensions/qq` as the executable template:

```python
def register(api):
    channel = MyProviderChannel(operator_settings)
    api.register_channel("my_provider", channel)
```

Bundled providers can extend the typed deployment profiles. Community plugins
can own root-environment settings and use their normal `gateway_config.json`
channel entry for admission, without modifying Core. Do not create another
auto-loader, Agent loop or tool registry. Startup/shutdown must release HTTP
sessions and any provider tasks.
Declare hot-reload support truthfully; current bot credentials require restart.

## 3. Protocol Projection And Verified Identity

`WebhookChannel.protocol_adapter()` reuses the current HTTP request projection
with provider metadata; the delivery Runtime registers it on first use.
Override it only for additional actual protocol needs, returning a
`channels.adapter_framework.ChannelAdapter`. Metadata describes wired features,
not every feature the provider offers. It is not webhook authentication.

Use existing IdentityStore proof pairing. The typed API accepts a running
registered provider, not a fixed QQ/Telegram list; raw namespaced ID claims are
blocked. Bind under `provider:account_id`.
Reuse the durable delivery ingress and existing Gateway chat/confirmation entry
points, never accept a local user ID, session ID, approval flag or tool name from
an untrusted callback. Group support needs explicit isolated ownership and member
admission, not implicit access to a private user's memory.

## 4. Tests And Documentation

- Verify raw-body tampering, missing/expired signatures, malformed and oversized input, bot loops and unsupported events.
- Verify expiring proof pairing, cross-account isolation, group ownership and revocation before execution/sending.
- Verify duplicate events, bounded admission, shutdown/restart, known rejection versus unknown delivery, and no model rerun on reply retry.
- Drive a real Gateway/ConversationService/ActionService chain with a deterministic model fixture, including sensitive-tool confirmation.
- Add the provider's real setup, callback registration, supported surfaces, credentials, limitations and acceptance checklist under `docs/channels/`.

Provider payload parsing and admission are Runtime work, not a new LLM classifier.
Model language understanding, Agent decisions, Memory and tool safety remain in
their current services.
