from gateway.memory_recall_utils import (
    build_recall_reason,
    parse_candidate_datetime,
    resolve_recall_policy,
    source_layer_to_memory_type,
)
from gateway.memory_text_utils import (
    build_semantic_keys,
    extract_json_object,
    normalize_candidates,
    normalize_content,
)


def test_memory_text_utils_normalize_and_extract():
    assert normalize_content("  A   B ") == "a b"
    obj = extract_json_object("x {\"ok\":true} y")
    assert obj and obj.get("ok") is True


def test_memory_text_utils_candidate_normalization():
    out = normalize_candidates(
        [{"type": "preference", "content": "Prefer concise", "semantic_keys": ["concise"]}]
    )
    assert out and out[0]["type"] == "preference"
    keys = build_semantic_keys("prefer concise answers", llm_keys=["concise"])
    assert "concise" in keys


def test_memory_recall_policy_and_mapping():
    policy = resolve_recall_policy(mode="fast", cfg={}, request_top_k=3)
    assert policy["top_k"] == 3
    assert source_layer_to_memory_type("summary") == "semantic"
    assert build_recall_reason({"source_layer": "recent"}, mode="fast", session_id="s1") == "recent_session_context"
    assert parse_candidate_datetime("2026-01-01T00:00:00Z") is not None
