import pytest

from gateway.reasoning_service import ReasoningService
from gateway.reasoning_state_machine import (
    FAILED,
    PENDING,
    RUNNING,
    WAITING_HUMAN,
    WAITING_TOOL,
    can_transition,
)


class DummyConversationCore:
    async def call_llm(self, messages, user_config=None, user_id=None):
        return {"content": "{}"}


def _service() -> ReasoningService:
    return ReasoningService(conversation_core=DummyConversationCore())


def test_reasoning_node_initial_status_is_pending():
    svc = _service()
    tree = svc._create_tree(session_id="s1", user_id="u1", root_goal="goal")
    node = svc._add_node(tree, parent_id=tree.root_node_id, kind="thought", title="step1")

    assert node.status == PENDING


def test_reasoning_node_transition_rules_are_validated():
    assert can_transition(PENDING, RUNNING) is True
    assert can_transition(RUNNING, WAITING_TOOL) is True
    assert can_transition(WAITING_TOOL, RUNNING) is True
    assert can_transition(RUNNING, FAILED) is True
    assert can_transition(FAILED, RUNNING) is False


def test_waiting_tool_can_resume_to_running():
    svc = _service()
    tree = svc._create_tree(session_id="s1", user_id="u1", root_goal="goal")
    node = svc._add_node(tree, parent_id=tree.root_node_id, kind="thought", title="step1")

    svc._transition_node_status(tree=tree, node=node, target=RUNNING, reason="start")
    svc._transition_node_status(tree=tree, node=node, target=WAITING_TOOL, reason="tool")
    svc._resume_node_from_waiting_tool(tree=tree, node=node)

    assert node.status == RUNNING


def test_waiting_human_can_resume_to_running():
    svc = _service()
    tree = svc._create_tree(session_id="s1", user_id="u1", root_goal="goal")
    node = svc._add_node(tree, parent_id=tree.root_node_id, kind="thought", title="step1")

    svc._transition_node_status(tree=tree, node=node, target=RUNNING, reason="start")
    svc._transition_node_status(tree=tree, node=node, target=WAITING_HUMAN, reason="human gate")
    svc._resume_node_from_waiting_human(tree=tree, node=node, approved=True)

    assert node.status == RUNNING


def test_failed_status_is_terminal_for_transition():
    svc = _service()
    tree = svc._create_tree(session_id="s1", user_id="u1", root_goal="goal")
    node = svc._add_node(tree, parent_id=tree.root_node_id, kind="thought", title="step1")

    svc._transition_node_status(tree=tree, node=node, target=RUNNING, reason="start")
    svc._transition_node_status(tree=tree, node=node, target=FAILED, reason="error")

    with pytest.raises(ValueError):
        svc._transition_node_status(tree=tree, node=node, target=RUNNING, reason="retry")


def test_node_snapshot_is_serializable_for_recovery():
    svc = _service()
    tree = svc._create_tree(session_id="s1", user_id="u1", root_goal="goal")
    node = svc._add_node(tree, parent_id=tree.root_node_id, kind="thought", title="step1")

    svc._transition_node_status(
        tree=tree,
        node=node,
        target=RUNNING,
        reason="start",
        checkpoint={"phase": "start"},
    )
    node.tool_calls.append({"tool_name": "search.web", "ok": True})

    snap = svc._snapshot_node(node)

    assert snap["status"] == RUNNING
    assert snap["checkpoint"]["phase"] == "start"
    assert isinstance(snap["tool_calls"], list)
