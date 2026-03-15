from memory.backends.sqlite_graph import SqliteGraphMemoryStore


def test_sqlite_graph_related_recall_via_recursive_cte(tmp_path):
    db_path = tmp_path / "mem.db"
    store = SqliteGraphMemoryStore(str(db_path))

    assert store.add_message(
        session_id="s1",
        role="user",
        content="Tokio runtime tuning guide for production services",
        user_id="u1",
        metadata={"memory_type": "project_state", "source_layer": "summary"},
    )
    assert store.add_message(
        session_id="s2",
        role="user",
        content="Rust async stack usually relies on tokio for scheduling",
        user_id="u1",
        metadata={"memory_type": "semantic", "source_layer": "concept"},
    )

    # Query token "runtime" directly hits the first memory.
    # Graph expansion through token co-occurrence should pull the second row via "tokio".
    rows = store.collect_recall_candidates(
        query="runtime optimization",
        session_id="s3",
        user_id="u1",
        top_k=8,
        mode="deep",
    )

    contents = [str(r.get("content") or "") for r in rows]
    assert any("runtime tuning guide" in x.lower() for x in contents)
    assert any("rust async stack" in x.lower() for x in contents)

