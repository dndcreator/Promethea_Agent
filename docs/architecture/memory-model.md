# Memory Model (Backlog 007)

## Goal

Introduce a unified memory write gate so long-term memory writes are explicit, reviewable, and safer.

## Core Contracts

- `MemoryWriteRequest`
- `MemoryWriteDecision`
- `MemoryWriteGate`

Implementation:

- `gateway/memory_gate.py`
- `gateway/memory_service.py`

## MemoryWriteRequest

Request fields include:

- source text and turn context
- proposed memory type
- extracted content
- confidence
- related entities
- run/session/user metadata
- conflict candidates

## MemoryWriteDecision

Decision fields include:

- `decision`: `allow | deny | defer`
- `target_memory_layer`
- `reason` and `reasons`
- `conflict_candidates`
- `requires_user_confirmation`

## Decision Behavior (current baseline)

- deny speculative or low-confidence content
- defer short-lived context into `working_memory` semantics
- defer conflicting writes and mark `requires_user_confirmation=true`
- allow durable factual candidates

## Runtime Integration

Long-term writes from `interaction.completed` now pass through `MemoryWriteGate` before persistence.

When evaluated, runtime emits `memory.write.decided` with:

- decision status
- reason
- target layer
- conflict markers
- whether the write was persisted

## Scope Notes

This baseline focuses on write governance, not full conflict resolution UX.
Future steps can add:

- conflict resolver
- memory inspector/editor integration
- layer-specific retention policies

## Recall Policy And Inspector (Backlog 011)

Runtime memory now includes a structured recall layer in addition to write gating.

Core contracts:

- `MemoryRecallRequest`
- `MemoryRecallResult`
- `RecalledMemoryItem`
- `DroppedRecallCandidate`

Implementation:

- `gateway/memory_recall_schema.py`
- `gateway/memory_service.py`
- `gateway/conversation_pipeline.py`

Inspector foundation:

- in-memory recall run history per process
- run list query and run detail query via gateway methods
- each recall run records selected items, dropped candidates, filters, strategy, and metrics
