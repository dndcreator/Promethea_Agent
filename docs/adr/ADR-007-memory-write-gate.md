# ADR-007: Memory Write Gate

## Status

Accepted

## Date

2026-03-11

## Context

Memory extraction can produce noisy or speculative candidates. Without a unified gate, long-term memory quality degrades over time and is hard to audit.

## Decision

Introduce an explicit memory write gate with typed request/decision contracts:

- `MemoryWriteRequest`
- `MemoryWriteDecision`
- `MemoryWriteGate`

Integrate the gate into persistent write path of `interaction.completed` in `MemoryService`.
Emit `memory.write.decided` for all gate outcomes (`allow|deny|defer`).

## Consequences

### Positive

- Long-term writes are explicit and auditable.
- Speculative/short-lived/conflicting content is blocked or deferred early.
- Future conflict handling and inspector features have stable input contracts.

### Trade-offs

- Conservative defaults may reduce recall in edge cases.
- Additional per-candidate checks add small runtime overhead.

## Implementation Mapping

- `gateway/memory_gate.py`
- `gateway/memory_service.py`
- `gateway/server.py`
- `tests/test_memory_write_gate.py`
- `docs/architecture/memory-model.md`
