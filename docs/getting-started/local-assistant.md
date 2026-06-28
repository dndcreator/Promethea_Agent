# Local Assistant Basics

Promethea can be used as a local assistant shell while preserving protocol-first runtime architecture.

## UI Entry

- Open `http://127.0.0.1:5173`

## CLI Entry

- `promethea chat send "你好"`
- `promethea status services`

## Key Principle

UI and CLI are clients. Backend runtime is canonical capability.

That means:
- workflows, tools, memory, and reasoning should remain callable via API surfaces
- UI-only features should be visual-only, not core runtime logic

See:
- [Runtime Overview](../runtime-overview.md)
- [Protocol Surface](../reference/protocol-surface.md)
