# Playbook: How to Change the Memory Backend

This guide covers switching the active memory backend, including live migration without data loss.

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
# {
#   "ok": True,
#   "mode": "cutover",
#   "active_backend": "sqlite_graph",
#   "items_migrated": 1842,
#   "checkpoint": "2026-03-15T..."
# }
```

### Option B: Dual-write period + cutover

Write to both backends simultaneously until you are confident the new backend is healthy.

```python
# Phase 1: Configure dual-write
adapter.configure_migration(
    mode="dual_write",
    source_backend="neo4j",
    target_backend="sqlite_graph",
)

# Run your workload for a while...
# Both backends receive all new messages.

# Phase 2: Verify the new backend looks correct
mef = adapter.export_mef(target_backend="sqlite_graph")
print(f"Items in sqlite_graph: {len(mef['memory_items'])}")

# Phase 3: Cut over
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
# {"backend": "neo4j", "status": "ready"}
```
