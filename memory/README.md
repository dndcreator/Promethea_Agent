# Memory Module

The `memory` module transforms raw conversation turns into long-lived structured memory and recalls relevant information in future turns.

## Goals

- reliable writes
- useful retrieval
- sustainable maintenance through clustering, summarization, and forgetting

## Key Files

- `memory/adapter.py`: external entrypoint integrated with gateway
- `memory/hot_layer.py`: near-term memory write path
- `memory/warm_layer.py`: clustering and stabilization
- `memory/cold_layer.py`: summarization and compression
- `memory/forgetting.py`: decay and cleanup policy
- `memory/auto_recall.py`: retrieval logic and layer ranking
- `memory/llm_extractor.py`: fact/entity extraction
- `memory/session_scope.py`: user/session scoping helpers
- `memory/neo4j_connector.py`: Neo4j access wrapper
- `memory/models.py`: graph node/edge models

## Architecture And Flow

Write path:

1. A full user-assistant turn completes.
2. The extractor produces facts/entities.
3. Hot-layer nodes are persisted.
4. Warm clustering and cold summarization run asynchronously.
5. Forgetting applies decay and cleanup policy.

Recall path:

1. Decide whether recall should run.
2. Search user-scoped memory.
3. Aggregate multi-layer results: summary, concept, direct, related, and recent.
4. Inject useful results into model context.

## Store Backends

The memory adapter supports backend switching through config:

- `memory.store_backend = neo4j`
- `memory.store_backend = sqlite_graph`
- `memory.store_backend = flat_memory`

Neo4j is the intended full graph backend for the public preview. Fallback backends are explicit degraded/local alternatives, not silent replacements.

Migration controls:

- `memory.migration.mode = off | dual_write | cutover`
- `memory.migration.source_backend`
- `memory.migration.target_backend`
- `memory.migration.checkpoint`

All backends expose `export_mef()` / `import_mef()` using a common Memory Exchange Format (MEF) envelope.

## Example

Session A: user says "My name is Wang Er, I am 26."
Session B: user asks "How old am I?"

If write and recall are healthy, cross-session recall should retrieve age=26.

## Operational Notes

- Isolation boundary is user-level, not session-level.
- Recall should primarily solve long-horizon context gaps.
- Extraction failures should not crash primary chat flow.

## Change Notes

- Define ranking intent before changing `auto_recall.py`.
- Handle Neo4j missing relationship/property warnings carefully.
- Run forgetting regressions after decay policy changes.
