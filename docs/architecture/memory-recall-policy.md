# Memory Recall Policy (Backlog 011)

## Goal

Standardize memory recall as an explicit, inspectable runtime step with stable request/result contracts.

## Core Contracts

- `MemoryRecallRequest`
- `MemoryRecallResult`
- `RecalledMemoryItem`
- `DroppedRecallCandidate`

## Policy Baseline

Mode-specific recall defaults:

- `fast`: smaller top-k and narrower layer scope
- `deep`: wider layer scope and larger top-k
- `workflow`: prioritize workflow-relevant memory usage

Recall filtering baseline:

- layer filtering
- namespace filtering
- duplicate filtering
- staleness filtering
- top-k budget filtering

## Explainability

Each selected item carries:

- `recall_reason`
- `source_layer`
- relevance/confidence fields
- staleness/conflict flags

Each dropped candidate records:

- drop reason
- short detail payload for inspector/debug usage

## Runtime Integration

Main path now routes memory recall through `MemoryService.recall_memory`.
`get_context` remains as a compatibility wrapper over the structured recall result.

## Inspector Foundation

Gateway methods:

- `memory.recall.runs`
- `memory.recall.inspect`

HTTP endpoints:

- `GET /memory/recall/runs`
- `GET /memory/recall/{target_request_id}`
