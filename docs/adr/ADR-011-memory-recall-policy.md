# ADR-011: Memory Recall Policy And Inspector Foundation

## Status

Accepted

## Date

2026-03-12

## Context

Memory retrieval previously returned plain context text directly, without standardized request/result contracts, per-item recall reasons, or inspector-ready dropped-candidate traces.

This made long-term recall behavior hard to diagnose and hard to tune.

## Decision

Introduce a structured memory recall boundary with:

- `MemoryRecallRequest`
- `MemoryRecallResult`
- item-level explainability fields (`recall_reason`, layer, relevance/confidence)
- dropped-candidate records with explicit reasons

Add recall inspector query capability at gateway level:

- `memory.recall.runs`
- `memory.recall.inspect`

## Consequences

### Positive

- recall behavior is now explainable and inspectable
- prompt memory injection can consume a stable recall output contract
- memory tuning can use concrete dropped-candidate reasons

### Trade-offs

- recall inspector history is process-memory only in this iteration
- scoring/filtering logic is heuristic baseline and should evolve incrementally

## Implementation Mapping

- `gateway/memory_recall_schema.py`
- `gateway/memory_service.py`
- `gateway/conversation_pipeline.py`
- `gateway/server.py`
- `gateway/http/routes/memory.py`
- `tests/test_memory_recall_policy_inspector.py`
- `docs/architecture/memory-recall-policy.md`
