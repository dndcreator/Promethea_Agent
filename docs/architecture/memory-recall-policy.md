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

## Hybrid Candidate Retrieval

`MemoryService` consumes the adapter's structured `collect_recall_candidates`
contract directly. Backend lookup uses deterministic lexical matching, including
shared Chinese character bigrams, not an additional LLM entity-extraction call.
Neo4j lookup includes owned Messages, Concepts and Summaries and bounded graph
neighbors; SQLite retains its existing lightweight graph traversal. A query miss
does not become an unrelated recent-memory match.

Optional semantic retrieval is internal to memory: `SemanticRecall` owns a bounded
background reconciliation worker and `EmbeddingEncoder` owns local/compatible API
I/O. `Neo4jVectorIndex` stores derived properties on existing memory nodes, with
separate user/model namespaces. ANN candidate generation is user-scoped before
top-k, not a global search followed by owner filtering. Content equality fences
both writes and reads against stale embeddings. Archived/superseded sources are
excluded and obsolete derived namespaces are retired after replacement indexing.

Reciprocal rank fusion combines lexical/graph and vector rankings; existing recall
policy still controls layer/age/namespace/deduplication and final context budget.
Later stages preserve that fused score instead of silently replacing it with text
overlap. Returned metadata records retrieval channels. These scores are ranking
signals, not calibrated probabilities or proof that a memory is true.

`SelfModelService` remains responsible for query decomposition and cognition
reduction. Its passive search stays deterministic and does not activate embedding
inference. Explicit recall and workbench search may use the enhanced CandidatePool.
Temporary cognition snapshots do not become memory through indexing.

See [configuration](../configuration.md#optional-memory-embeddings) for explicit
download, optional dependencies, endpoint privacy, fallback and lifecycle limits.

## Inspector Foundation

Gateway methods:

- `memory.recall.runs`
- `memory.recall.inspect`

HTTP endpoints:

- `GET /memory/recall/runs`
- `GET /memory/recall/{target_request_id}`
