# Telegram Channel Status and Integration Notes

This page documents the current Telegram state in this repository.

## Current implementation status

Implemented now:

- Telegram channel adapter exists:
  - `channels/adapters/telegram_adapter.py`
- Adapter registry includes `telegram`.
- Adapter responsibilities:
  - normalize inbound payload into internal channel request shape
  - map user identity fields
  - enforce basic permission checks for missing identity
  - build stable session key for Telegram chat/message scope

Not implemented as first-party runtime in this repository:

- No built-in Telegram bot token lifecycle/config flow in `config.py`
- No built-in webhook registration handler for Telegram bot API
- No documented polling worker that starts from `TELEGRAM__...` env keys

## Practical guidance (today)

If you need Telegram in production now, use an external ingress bridge:

1. Receive Telegram webhook updates in your own bridge service.
2. Map Telegram payload to the adapter contract fields.
3. Forward normalized requests to Promethea HTTP endpoints.

## Adapter payload hints

Common inbound fields handled by the adapter include:

- `telegram_user_id` (or fallback `sender_id`)
- `chat_id`
- `text`/message payload data

Session key is derived from chat/message identity to keep conversation grouping stable.

## On configuration keys

You may keep prospective env keys (for example `TELEGRAM__BOT_TOKEN`) in deployment notes,
but they are currently treated as reserved planning keys unless you add runtime wiring.

## Related files

- `channels/adapters/telegram_adapter.py`
- `channels/adapter_registry.py`
- `docs/configuration.md`
