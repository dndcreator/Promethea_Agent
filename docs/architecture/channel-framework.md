# Channel Framework (Backlog 013)

## Goal

Introduce a unified Channel Adapter Framework so entry channels map to the same `GatewayRequest` and `GatewayResponse` contracts.

## Unified Adapter Interface

`ChannelAdapter` defines:

- `ingest_message(raw_input) -> GatewayRequest`
- `normalize_identity(raw_input) -> IdentityContext`
- `build_session_key(raw_input) -> str`
- `emit_response(gateway_response) -> ChannelOutput`
- `emit_stream_chunk(chunk) -> ChannelChunk`
- `permission_check(identity_context) -> PermissionDecision`

## Metadata Contract

`ChannelMetadata` captures channel capabilities:

- channel id/type
- streaming support
- attachment/rich artifact support
- reaction/voice support
- session model

## MVP Adapters

- `WebChannelAdapter`
- `HttpApiChannelAdapter`
- `TelegramChannelAdapter` (validation channel for framework extensibility)

## Registry

`ChannelAdapterRegistry` hosts adapters and supports lookup by `channel_id`.

## Runtime Integration

- `GatewayServer._handle_chat` now resolves a channel adapter first, then performs identity normalization, permission check, and request/response mapping through adapter.
- HTTP `/chat` non-stream path also maps via `HttpApiChannelAdapter` before dispatching gateway method.

## Boundary

Channel-specific identity/session/response details live in adapters; runtime conversation logic remains channel-agnostic.
