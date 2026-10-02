# Memory Model (Backlog 007)

## Goal

Provide durable, governed memory as the evidence base for the agent's user-scoped cognition and Self Model.

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

## Four-Layer Pipeline (2026-04 Upgrade)

Memory pipeline is now split by responsibility:

1. `L0 raw_log`: append-only write-ahead log (`memory/raw_log.jsonl`)
2. `L1 hot`: online structured memory write (current store backend)
3. `L2 warm`: concept clustering and stabilization
4. `L3 cold`: summary consolidation and forgetting/decay policy

Operational rules:

- write-gated candidates are persisted to `L0` first
- hot writes can be deferred and replayed from raw log
- idle/background consolidation improves warm/cold quality
- replay checkpoint (`memory/raw_log.state.json`) supports crash recovery and abrupt-exit continuity

`L0 raw_log` is the first memory persistence layer, not a temporary log and not a test
artifact. Treat `memory/raw_log.jsonl` and `memory/raw_log.state.json` as runtime
memory state. Cleanup scripts and test teardown must not remove them; tests that need
disposable raw-log data should redirect the raw-log paths into their own temp directory.

## Cognition and Self Model

Cognition is not a fourth memory layer. The memory pipeline stores governed records and
history; the Self Model projects those records into a current, user-scoped view that the
runtime and UI can consume.

The unified Self Model has three owned projections and one downstream consumer:

- `self`: stable runtime identity and architecture knowledge derived from project docs
- `cognition`: current, evolving, uncertain, and historical interpretations projected from user memory
- `capabilities`: live capability and tool knowledge
- Self Evolve consumes the model to author append-only capability packages; it does not own cognition or modify Core

`GET /api/memory/cognition` returns the public `CognitionBundle`. It does not duplicate
memory or introduce a new persistence backend. The projection uses structured memory
types and metadata, not language-specific keyword rules. Pending write proposals appear
as uncertain cognition requiring review.

User cognition is assembled at request time and is never written into the repository-level
`memory/self_model.json`. That file remains a non-user-specific architecture/capability model.
`ConversationService` places one bounded projection in `RunContext`; `PromptAssembler`,
Reasoning tools, and detached workflows then inherit that same context through existing runtime
boundaries. Runtime events continue to flow into MemoryService and the hippocampus for later
consolidation rather than being written back by SelfModelService directly.

### Adaptive cognitive recall

`SelfModelService` owns active cognition calculation while `MemoryService`
remains the source of governed candidates. The model-facing `cognition.recall`
capability requests one shared candidate pool, preserves critical records in a
bounded skip buffer, and selects Fast, Adaptive, or Deep reduction under explicit
channel, depth, concurrency, call-count, and deadline budgets.

Adaptive and Deep modes may decompose the query into independent kernels. Supplied
facets bypass decomposition. Deep mode groups records into graph-aware receptive
fields using available community, cluster, revision-chain, relationship, and
layer metadata before at most one upper reduction layer. Missing graph metadata
degrades to bounded layer grouping.

The resulting `CognitionSnapshot` is attached to the current `RunContext` and may
flow into reasoning or a detached workflow. It is never a second memory store.
Durable insights must be proposed through Hippocampus and pass the existing
Memory write gate.

Completed, non-degraded adaptive cognition can also leave a bounded hint in the
Hippocampus checkpoint state. A hint contains only the temporary synthesis and its
source memory IDs. Replay uses it to prioritize records and avoid repeating exploratory
work, but treats the text as an untrusted hypothesis: only re-read memory records may
support a durable insight. Consumed hints are removed after the replay cycle.

## Procedural Memory (Basal Ganglia)

In addition to user memory layers above, runtime now persists procedural reasoning/action assets under:

- `brain/basal_ganglia/reasoning_templates/*.templates.json`
- `brain/basal_ganglia/reasoning_templates/*.paths.jsonl`
- `brain/basal_ganglia/moirai_runs/*.json`

These artifacts are not generic chat memory. They are "how to do this class of task" assets:

- successful reasoning templates
- action templates
- execution mind graph snapshots
- optimization profile episodes

## ExecutionMindGraph (LLM-facing procedural graph)

Each successful reasoning template may include `execution_mind_graph`:

- `goal`
- `nodes` (intent/capability-oriented action nodes)
- `edges` (normal/fallback transitions)
- `fallback_policies`

Design intent:

- store intent/capability, not hard-bind to one specific tool
- replay should prefer semantic capability match, then exact historical tool as fallback
- failed replay should re-enter reasoning and re-plan dynamically
