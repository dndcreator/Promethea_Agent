# Memory Backends

Promethea supports three pluggable memory backends, all implementing the same `MemoryStore` interface.  
You can switch between them without changing any application code — including live migration with optional dual-write.

---

## Interface contract

All backends implement `memory/backends/base.py`:

```python
class MemoryStore(ABC):
    def is_ready(self) -> bool: ...
    def add_message(*, session_id, role, content, user_id, metadata) -> bool: ...
    def get_context(*, query, session_id, user_id) -> str: ...
    def collect_recall_candidates(*, query, session_id, user_id, top_k, mode) -> List[Dict]: ...
    def export_mef(*, user_id) -> Dict: ...
    def import_mef(payload, *, merge) -> Dict: ...
```

---

## `flat_memory` — JSONL file

**File:** `memory/backends/flat_memory.py`

Simplest possible backend. Every message is appended as a JSON line.

- No external dependencies
- Recall is linear scan with token overlap scoring
- No graph structure
- `export_mef` / `import_mef` use the same JSONL format

**Best for:** First-time users, CI tests, environments without a database.

**Configuration:**
```bash
MEMORY__STORE_BACKEND=flat_memory
MEMORY__FLAT_MEMORY_PATH=memory/flat_memory.jsonl
```

---

## `sqlite_graph` — SQLite with graph recall

**File:** `memory/backends/sqlite_graph.py`

SQLite database with four tables: `nodes`, `edges`, `memory_items`, `memory_links`.

Every message is tokenized and token co-occurrence edges are built automatically.  
Recall uses a recursive CTE walk from seed nodes:

```sql
WITH RECURSIVE walk(node_id, depth, score, path) AS (
    SELECT node_id, 0, seed_score, node_id FROM seed_nodes
    UNION ALL
    SELECT e.dst_node_id, w.depth + 1, w.score * e.weight * 0.78, ...
    FROM walk w JOIN edges e ON ...
    WHERE w.depth < 2 AND instr(w.path, e.dst_node_id) = 0
)
SELECT ml.memory_id, MAX(w.score * ml.weight) AS graph_score ...
```

This means: if a user discussed "tokio" and "runtime" in separate sessions, a query for "runtime optimization" can surface both memories through the shared token node.

**Recall modes:**
- `fast`: lexical seed + graph expansion (depth 2)
- `deep`: same algorithm, wider candidate pool
- `workflow`: same as deep (future: checkpoint-aware)

**Best for:** Personal use, development, users who want semantic + graph recall without running Neo4j.

**Configuration:**
```bash
MEMORY__STORE_BACKEND=sqlite_graph
MEMORY__SQLITE_GRAPH_PATH=memory/sqlite_graph.db
```

---

## `neo4j` — Full layered memory stack

**File:** `memory/backends/neo4j_store.py`

Wraps the full hot/warm/cold/forgetting memory stack backed by Neo4j.

- **Hot layer** (`memory/hot_layer.py`): recent message storage, LLM-based entity extraction
- **Warm layer** (`memory/warm_layer.py`): clustering and concept stabilization
- **Cold layer** (`memory/cold_layer.py`): incremental summarization
- **Forgetting** (`memory/forgetting.py`): time-decay, cleanup, episodic pruning

All operations are user-scoped. `scoped_session_id(session_id, user_id)` ensures no cross-user contamination.

**Best for:** Production deployments, multi-session long-term use, profile-level memory.

**Configuration:**
```bash
MEMORY__STORE_BACKEND=neo4j
MEMORY__NEO4J__ENABLED=true
MEMORY__NEO4J__URI=bolt://localhost:7687
MEMORY__NEO4J__USERNAME=neo4j
MEMORY__NEO4J__PASSWORD=your-password
```

---

## MEF — Memory Exchange Format

All three backends support lossless export and import via MEF.

### Structure

```json
{
  "version": "1.0",
  "source_backend": "sqlite_graph",
  "exported_at": "2026-03-15T...",
  "memory_items": [...],
  "nodes": [...],
  "edges": [...],
  "metadata": {}
}
```

`flat_memory` exports `nodes: []` and `edges: []` since it has no graph.  
`sqlite_graph` exports the full graph.  
`neo4j` exports whatever the Neo4j store returns.

### Live migration

```python
from memory.adapter import get_memory_adapter

adapter = get_memory_adapter()

# One-step cutover (no downtime window):
result = adapter.migrate_backend("sqlite_graph", mode="cutover")
# {"ok": True, "mode": "cutover", "active_backend": "sqlite_graph", ...}

# Two-phase migration with dual-write:
adapter.configure_migration(mode="dual_write", source_backend="neo4j", target_backend="sqlite_graph")
# ... after validation:
adapter.migrate_backend("sqlite_graph", mode="cutover")
```

During dual-write, both backends receive all new messages.  
After cutover, the adapter switches `self.store` to the new backend.

---

## Choosing a backend

```
Do you want zero external dependencies?
  └─ Yes → flat_memory (no graph recall) or sqlite_graph (with graph recall)

Do you need graph-based semantic recall?
  └─ Yes → sqlite_graph (local) or neo4j (production)

Do you need multi-session hot/warm/cold layering and forgetting?
  └─ Yes → neo4j only

Do you need to run in CI without any setup?
  └─ flat_memory
```
