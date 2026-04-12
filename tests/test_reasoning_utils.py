from gateway.reasoning_utils import (
    extract_json_object,
    format_recent_messages,
    map_plan_steps_to_moirai,
    merge_steps,
    safe_user_segment,
    to_bool,
)


def test_extract_json_object_returns_dict():
    out = extract_json_object("xx {\"a\":1} yy")
    assert out.get("a") == 1


def test_merge_steps_dedup_by_title_goal():
    rows = merge_steps(
        [{"title": "A", "goal": "G"}, {"title": "B", "goal": "H"}],
        [{"title": "A", "goal": "G"}, {"title": "C", "goal": "I"}],
        limit=10,
    )
    assert len(rows) == 3


def test_map_plan_steps_to_moirai_contains_probe_when_required():
    rows = map_plan_steps_to_moirai(
        [{"title": "T1", "goal": "G1", "requires_tools": True, "tool_intent": "search"}]
    )
    assert any(r.get("kind") == "mcp_call" for r in rows)


def test_reasoning_utils_basic_format_and_bool():
    text = format_recent_messages([{"role": "user", "content": "hello"}])
    assert "user: hello" in text
    assert to_bool("yes") is True
    assert safe_user_segment("a/b") == "a_b"
