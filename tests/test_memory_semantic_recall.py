from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import MemoryEmbeddingConfig
from gateway.memory_recall_schema import MemoryRecallRequest
from gateway.memory_service import MemoryService
from memory.backends.neo4j_retrieval import Neo4jVectorIndex
from memory.backends.neo4j_store import Neo4jMemoryStore
from memory.backends.sqlite_graph import SqliteGraphMemoryStore
from memory.embedding import EmbeddingEncoder, EmbeddingUnavailable, fingerprint, validate_vectors
from memory.retrieval import fuse_candidates, tokenize_text
from memory.semantic_recall import SemanticRecall


def test_chinese_retrieval_uses_shared_subwords_without_language_model():
    assert "北京" in tokenize_text("我之前住在北京")
    assert "北京" in tokenize_text("北京的住址是什么")
    assert tokenize_text("run_id ABC") == ["run", "id", "abc"]


def test_sqlite_structured_recall_chinese_isolated_and_no_recent_filler(tmp_path):
    store = SqliteGraphMemoryStore(str(tmp_path / "memory.db"))
    for user, text in [("u1", "我住在北京海淀"), ("u2", "我住在北京朝阳")]:
        store.add_message(session_id="s1", role="user", content=text, user_id=user, metadata={"memory_type": "identity"})
    rows = store.collect_recall_candidates(query="北京的住址", user_id="u1", session_id="s2")
    assert rows and all(row["owner_user_id"] == "u1" and "朝阳" not in row["content"] for row in rows)
    assert store.collect_recall_candidates(query="火星科研站", user_id="u1", session_id="s1") == []
    store.delete_memory_entry(user_id="u1", memory_id=rows[0]["memory_id"])
    assert not store.collect_recall_candidates(query="北京", user_id="u1", session_id="s1")


def test_rrf_preserves_semantic_ranking_and_deduplicates():
    first = {"memory_id": "a", "content": "A"}
    second = {"memory_id": "b", "content": "B", "retrieval_channels": ["vector"]}
    rows = fuse_candidates([first, first, second], [second])
    assert [row["memory_id"] for row in rows] == ["b", "a"]
    assert 0 < rows[1]["retrieval_score"] < rows[0]["retrieval_score"] <= 1


class Adapter:
    def is_enabled(self):
        return True

    def collect_recall_candidates(self, request):
        return [{"memory_id": "literal", "content": "北京", "source_layer": "direct", "owner_user_id": request.user_id}]


@pytest.mark.asyncio
async def test_service_uses_structured_candidates_not_extractor_and_preserves_fusion():
    adapter = Adapter()
    adapter.recall_engine = Mock()
    service = MemoryService(memory_adapter=adapter)
    semantic = {"memory_id": "semantic", "content": "首都的住所", "source_layer": "direct", "owner_user_id": "u1"}
    service.semantic_recall.search = lambda *args: [semantic]
    pool = service.retrieve_candidates(query="北京", session_id="s1", user_id="u1")
    scores = {row["memory_id"]: row["relevance_score"] for row in pool["candidates"]}
    assert scores["semantic"] == scores["literal"]
    adapter.recall_engine.extractor.extract.assert_not_called()
    result = await service.recall_memory(MemoryRecallRequest(request_id="r", trace_id="t", session_id="s1", user_id="u1", query_text="北京", mode="deep"))
    assert len(result.memory_records) == 2
    assert result.memory_records[0].relevance_score == result.memory_records[1].relevance_score


def test_service_drops_superseded_and_cross_user_candidates():
    adapter = Adapter()
    adapter.collect_recall_candidates = lambda request: [
        {"memory_id": "old", "content": "旧住址", "status": "archived", "owner_user_id": "u1"},
        {"memory_id": "other", "content": "私密", "owner_user_id": "u2"},
        {"memory_id": "updated", "content": "历史地址", "superseded_by": "new", "owner_user_id": "u1"},
    ]
    service = MemoryService(memory_adapter=adapter)
    service.semantic_recall.search = lambda *args: []
    assert service.retrieve_candidates(query="地址", session_id="s1", user_id="u1")["candidates"] == []


def test_vector_identity_includes_model_revision_and_endpoint_not_key():
    base = MemoryEmbeddingConfig(provider="local")
    assert fingerprint(base) != fingerprint(base.model_copy(update={"revision": "other"}))
    assert fingerprint(base) != fingerprint(base.model_copy(update={"base_url": "http://localhost:11434/v1"}))
    assert fingerprint(base) == fingerprint(base.model_copy(update={"api_key": "secret"}))


@pytest.mark.parametrize("values,count", [([[float("nan")]], 1), ([[0, 0]], 1), ([[1], [1, 2]], 2), ([[1]], 2), ([[float("inf")]], 1)])
def test_invalid_embeddings_fail_closed(values, count):
    with pytest.raises(EmbeddingUnavailable):
        validate_vectors(values, count)


def test_embedding_normalization():
    values = validate_vectors([[3, 4]], 1)
    assert math.isclose(sum(value ** 2 for value in values[0]), 1)


def test_local_missing_model_never_downloads_implicitly(tmp_path, monkeypatch):
    encoder = EmbeddingEncoder(tmp_path)
    monkeypatch.setattr("memory.embedding.importlib.util.find_spec", lambda name: object())
    monkeypatch.setattr(encoder, "download", Mock(side_effect=AssertionError("implicit download")))
    with pytest.raises(EmbeddingUnavailable, match="missing_model"):
        encoder.encode(["北京"], MemoryEmbeddingConfig(provider="local"))
    encoder.download.assert_not_called()


def test_download_is_explicit_pinned_size_bounded_and_safetensors_only(tmp_path, monkeypatch):
    import sys
    encoder = EmbeddingEncoder(tmp_path)
    settings = MemoryEmbeddingConfig(provider="local")
    monkeypatch.setattr("memory.embedding.importlib.util.find_spec", lambda name: object())
    files = [SimpleNamespace(rfilename="config.json", size=10), SimpleNamespace(rfilename="model.safetensors", size=100),
             SimpleNamespace(rfilename="pytorch_model.bin", size=100), SimpleNamespace(rfilename="evil.py", size=10)]
    calls = []
    def download(model, **kwargs):
        calls.append((model, kwargs))
        kwargs["local_dir"].mkdir(parents=True)
    module = SimpleNamespace(HfApi=lambda **kwargs: SimpleNamespace(model_info=lambda *args, **kwargs: SimpleNamespace(siblings=files)), snapshot_download=download)
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    encoder.download(settings)
    assert calls[0][1]["allow_patterns"] == ["config.json", "model.safetensors"]
    assert (encoder.path(settings) / ".complete").exists()
    with pytest.raises(EmbeddingUnavailable, match="pinned_model_revision_required"):
        encoder.download(settings.model_copy(update={"revision": "main"}))
    files[1].size = 9999999999
    with pytest.raises(EmbeddingUnavailable, match="download_limit_exceeded"):
        encoder.download(settings)


def test_neo4j_vector_index_is_user_scoped_and_fences_content_and_status():
    connector = Mock()
    connector.query.return_value = []
    index = Neo4jVectorIndex(connector)
    index.search("u1", "version", [1, 0], 8, .75)
    query, params = connector.query.call_args.args
    assert "OWNED_BY" in query and "superseded_by IS NULL" in query and "_text = m.content" in query
    assert params["uid"] == "user_u1"
    assert index.namespace("u1", "version")[1] == params["index"]
    assert index.namespace("u2", "version")[1] != params["index"]
    connector.query.return_value = [{"written": 0}]
    assert index.write("u1", "version", [{"memory_id": "m", "content": "old"}], [[1, 0]]) == 0
    query, params = connector.query.call_args.args
    assert "m.content = row.content" in query and "active" in query


class Index:
    def __init__(self):
        self.rows = [{"memory_id": "m1", "content": "我的偏好"}]
        self.writes = []

    def pending(self, *args):
        return self.rows

    def write(self, *args):
        self.writes.append(args)
        self.rows = []

    def counts(self, *args):
        return {"indexed": len(self.writes), "total": 1}

    def search(self, *args):
        return [{"memory_id": "m1"}]

    def prune(self, *args):
        return True

    def is_online(self, *args):
        return True


def test_reconciliation_recovers_from_existing_graph_and_failure_falls_back(tmp_path):
    settings = MemoryEmbeddingConfig(provider="local")
    index = Index()
    recall = SemanticRecall(index, settings_for_user=lambda user: settings.model_dump(), cache_dir=str(tmp_path))
    recall.status("u1")
    recall.encoder.encode = lambda texts, cfg: [[1, 0] for _ in texts]
    recall.encoder.is_loaded = lambda cfg: True
    recall.start = lambda: None
    recall.sync_once("u1")
    assert recall.status("u1")["index_state"] == "ready"
    assert recall.search("u1", "query", 8) == [{"memory_id": "m1"}]
    recall.encoder.encode = Mock(side_effect=RuntimeError("secret provider details"))
    assert recall.search("u1", "query", 8) == []
    assert recall.status("u1")["reason"] == "embedding_unavailable"
    recovered = SemanticRecall(index, settings_for_user=lambda user: settings.model_dump(), cache_dir=str(tmp_path))
    recovered.status("u1")
    recovered.sync_once("u1")
    assert recovered.status("u1")["indexed"] == 1


def test_inflight_config_change_and_shutdown_prevent_index_writes(tmp_path):
    cfg = MemoryEmbeddingConfig(provider="local").model_dump()
    index = Index()
    recall = SemanticRecall(index, settings_for_user=lambda user: cfg, cache_dir=str(tmp_path))
    recall.status("u1")
    def encode(*args):
        cfg["model"] = "another/model"
        return [[1, 0]]
    recall.encoder.encode = encode
    recall.sync_once("u1")
    assert not index.writes
    recall.stop()
    recall.sync_once("u1")
    assert not index.writes


def test_unsupported_backend_does_not_invoke_encoder(tmp_path):
    recall = SemanticRecall(None, settings_for_user=lambda user: MemoryEmbeddingConfig(provider="local").model_dump(), cache_dir=str(tmp_path))
    recall.encoder.encode = Mock(side_effect=AssertionError("must not encode"))
    assert recall.status("u1")["index_state"] == "unsupported"
    assert recall.search("u1", "query", 5) == []


def test_neo4j_keyword_recall_has_no_llm_and_keeps_summary_concept_types():
    connector = Mock()
    connector.query.side_effect = [[{"memory_id": "summary", "source_layer": "summary", "content": "北京"}], []]
    engine = Mock()
    store = Neo4jMemoryStore(adapter=None, connector=connector, recall_engine=engine)
    rows = store.collect_recall_candidates(query="北京的住址", session_id="s1", user_id="u1")
    assert rows[0]["source_layer"] == "summary"
    engine.extractor.extract.assert_not_called()
    query, params = connector.query.call_args_list[0].args
    assert "北京" in params["tokens"] and "SUMMARIZES" in query


def test_cold_and_busy_queries_use_fallback_without_blocking(tmp_path):
    settings = MemoryEmbeddingConfig(provider="local")
    recall = SemanticRecall(Index(), settings_for_user=lambda user: settings.model_dump(), cache_dir=str(tmp_path))
    recall.start = lambda: None
    recall.status("u1")
    recall._users["u1"].update(indexed=1, total=1, index_state="ready")
    recall.encoder.local_state = lambda settings: "ready"
    recall.encoder.encode = Mock(side_effect=AssertionError("cold query must not load synchronously"))
    assert recall.search("u1", "query", 4) == []
    assert recall._warmups == {"u1": "query"}
    recall._busy.acquire()
    try:
        assert recall.search("u1", "query", 4) == []
    finally:
        recall._busy.release()
    recall.encoder.encode.assert_not_called()


def test_index_does_not_report_ready_until_neo4j_index_is_online(tmp_path):
    settings = MemoryEmbeddingConfig(provider="local")
    index = Index()
    index.rows = []
    index.writes = ["existing"]
    index.is_online = lambda *args: False
    recall = SemanticRecall(index, settings_for_user=lambda user: settings.model_dump(), cache_dir=str(tmp_path))
    recall.sync_once("u1")
    assert recall.status("u1")["index_state"] == "indexing"


def test_export_does_not_transfer_derived_vector_properties_or_labels():
    import json
    connector = Mock()
    connector.query.side_effect = [[], [{"element_id": "1", "labels": ["Message", "MemoryVector_private"],
                                        "props": {"id": "m1", "content": "memory", "embedding_private": [1, 0], "embedding_private_text": "memory"}}], []]
    result = Neo4jMemoryStore(adapter=None, connector=connector).export_mef(user_id="u1")
    metadata = json.loads(result["nodes"][0]["metadata_json"])
    assert metadata["labels"] == ["Message"]
    assert not any(key.startswith("embedding_") for key in metadata["original_properties"])


def test_disabling_personal_memory_disables_semantic_provider():
    service = MemoryService(memory_adapter=Adapter())
    service._get_merged_config = lambda uid: {"memory": {"enabled": False, "embedding": {"provider": "openai-compatible"}}}
    assert service._embedding_settings_for_user("u1")["provider"] == "disabled"
