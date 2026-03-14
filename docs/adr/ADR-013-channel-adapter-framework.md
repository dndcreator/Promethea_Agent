# ADR-013: Channel Adapter Framework

- Status: Accepted
- Date: 2026-03-12
- Backlog: 013

## Context

Promethea needs multi-entry extensibility (web/http/desktop/im/voice) without scattering session/identity/response rules into runtime handlers.

## Decision

Add a unified adapter layer for channels:

- define `ChannelAdapter` interface and supporting identity/permission/metadata models
- add adapter registry with default adapters (`web`, `http_api`, `telegram`)
- route gateway chat entry through adapter mapping and permission check
- map HTTP non-stream chat through `http_api` adapter

## Why

This keeps channel differences in adapter modules and preserves runtime core as a protocol-driven control plane.

## Consequences

Positive:

- new channels can be added with minimal runtime impact
- identity/session normalization is centralized
- response mapping remains explicit and testable

Tradeoffs:

- one more abstraction layer to maintain
- adapters need governance to avoid drift from protocol contracts

## Follow-up

- migrate stream/chat-confirm paths to full adapter pipeline
- add desktop/tauri adapter and one enterprise IM adapter through same registry
- expose adapter metadata in channel inspector UI
