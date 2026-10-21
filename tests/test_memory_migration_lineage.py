import json

from memory.migration_lineage import MigrationLineageStore


def test_migration_lineage_keeps_snapshot_and_active_generation(tmp_path):
    store = MigrationLineageStore(tmp_path / "migrations")
    generation = store.begin(
        source_backend="neo4j",
        target_backend="sqlite_graph",
        snapshot={"source_backend": "neo4j", "memory_items": [{"id": "m1"}]},
    )

    assert generation["parent_generation_id"] is None
    snapshot_path = tmp_path / "migrations" / f"{generation['generation_id']}.mef.json"
    assert json.loads(snapshot_path.read_text(encoding="utf-8"))["memory_items"][0]["id"] == "m1"

    store.finish(generation["generation_id"], status="completed")
    state = store.snapshot()
    assert state["active_generation"] == generation["generation_id"]
    assert state["generations"][0]["status"] == "completed"


def test_failed_generation_does_not_replace_active_generation(tmp_path):
    store = MigrationLineageStore(tmp_path / "migrations")
    completed = store.begin(source_backend="neo4j", target_backend="sqlite_graph", snapshot={})
    store.finish(completed["generation_id"], status="completed")
    failed = store.begin(source_backend="sqlite_graph", target_backend="flat_memory", snapshot={})
    store.finish(failed["generation_id"], status="failed", error="write_error")

    state = store.snapshot()
    assert state["active_generation"] == completed["generation_id"]
    assert state["generations"][-1]["status"] == "failed"
    assert state["generations"][-1]["error"] == "write_error"
