# Playbook: How to Change the Memory Backend

This guide covers explicitly switching the active memory backend while preserving a source snapshot and migration lineage.

Account identity is independent of the selected Memory backend. The same user
continues to sign in with the same `user_id`; only the governed memory corpus
and its per-user ownership projections are migrated. Backends are separate lineage generations, not
automatically synchronized replicas, so repeated switching can lose
backend-specific structure or ranking behavior.

---

## Changing the backend (no existing data)

If you have no data to preserve (first run or fresh install):

1. Stop Promethea.
2. Edit `.env`:
   ```bash
   MEMORY__STORE_BACKEND=sqlite_graph   # or flat_memory or neo4j
   ```
3. Start Promethea.

That's it.

---

## Changing the backend with existing data

Use MEF (Memory Exchange Format) to migrate data.

### Option A: One-step cutover

All data is exported from the source backend, imported into the target, and the active backend switches immediately.

```python
from memory.adapter import get_memory_adapter

adapter = get_memory_adapter()
result = adapter.migrate_backend("sqlite_graph", mode="cutover")
print(result)
# {"ok": True, "mode": "cutover", "active_backend": "sqlite_graph",
#  "imported": {...}, "generation_id": "memgen_..."}
```

### Option B: Dual-write period + cutover

Write to both backends simultaneously until you are confident the new backend is healthy.

```python
# Phase 1: Copy the current generation and start the bounded dual-write window
result = adapter.migrate_backend("sqlite_graph", mode="dual_write")
print(result["generation_id"])

# Run your workload for a while...
# Both backends receive all new messages.

# Phase 2: Verify the new backend looks correct
mef = adapter.export_mef(target_backend="sqlite_graph")
print(f"Items in sqlite_graph: {len(mef['memory_items'])}")

# Phase 3: Cut over with a new source snapshot
result = adapter.migrate_backend("sqlite_graph", mode="cutover")
```

---

## Exporting your memory to MEF manually

```python
from memory.adapter import get_memory_adapter

adapter = get_memory_adapter()
mef = adapter.export_mef()

import json
with open("backup_2026-03-15.mef.json", "w") as f:
    json.dump(mef, f, indent=2)
```

---

## Importing MEF into a fresh backend

```python
import json
from memory.adapter import get_memory_adapter

with open("backup_2026-03-15.mef.json") as f:
    mef = json.load(f)

adapter = get_memory_adapter()
result = adapter.import_mef(mef, merge=True)
print(result)
# {"ok": True, "imported": 1842, "skipped": 0}
```

`merge=True` skips items that already exist (by ID).  
`merge=False` overwrites all existing data.

---

## Checklist for production migration

- [ ] Export MEF backup before starting
- [ ] Test import on a staging copy
- [ ] Choose dual-write mode if you need zero data loss during transition
- [ ] After cutover: update `MEMORY__STORE_BACKEND` in `.env`
- [ ] Verify `GET /api/memory/recall/runs` returns expected results
- [ ] Archive the MEF backup file

Do not change `MEMORY__STORE_BACKEND` in a user `secrets.env`. Backend selection
is process-wide, and an existing dataset must go through the explicit migration
operation before the deployment default is changed.

---

## Important: Neo4j setup

If migrating **to** Neo4j, the database must be running and reachable before starting migration:

```bash
MEMORY__NEO4J__ENABLED=true
MEMORY__NEO4J__URI=bolt://localhost:7687
MEMORY__NEO4J__PASSWORD=your-password
```

Test connectivity:
```bash
curl "http://127.0.0.1:8000/api/health/memory"
# {"status":"healthy","configured_backend":"neo4j","active_backend":"neo4j","ready":true,...}
```
