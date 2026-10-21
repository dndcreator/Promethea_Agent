import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentkit.tools.moirai.learning import MoiraiLearning
from gateway.conversation_service import ConversationService


def episode(run_id="run-1", capability="test.observe", *, ok=True, declined=False, ref=True):
    return {
        "action_run_id": run_id, "status": "success",
        "execution_path": [
            {"kind": "capability_request", "objective": "observe", "required_capabilities": [capability], "max_side_effect": "read_only"},
            {"kind": "tool_call", "tool_name": "test.observe", "args": {"api_key": "DO_NOT_STORE"}, "observation_id": "obs-1", "ok": ok},
        ],
        "observations": [{"observation_id": "obs-1", "ok": ok and not declined,
                          "structured_result": "DO_NOT_STORE",
                          "error": {"code": "USER_DECLINED", "category": "approval"} if declined else None}],
        "evidence_refs": ["obs-1"] if ref else [],
    }


class Backend:
    def __init__(self, rule=None):
        self.rule = rule
        self.batches = []

    async def distill(self, batch):
        self.batches.append(batch)
        return {"rules": [self.rule] if self.rule else []}


def rule(**updates):
    return {"rule_id": "", "level": "task", "instruction": "Inspect available observation capabilities; adapt if absent.",
            "capabilities": ["test.observe"], "support": ["run-1"], "counterexamples": [], **updates}


def test_episode_is_idempotent_isolated_and_does_not_equate_execution_with_goal(tmp_path):
    store = MoiraiLearning(tmp_path)
    assert store.record(user_id="alice", result=episode(), goal="inspect")
    assert not store.record(user_id="alice", result=episode(), goal="changed")
    assert store.episodes("bob") == []
    saved = store.episodes("alice")[0]
    assert saved["goal"] == "inspect"
    assert saved["goal_verification"] == "unknown"
    assert saved["attempts"][0]["used_as_evidence"]
    assert "DO_NOT_STORE" not in str(saved)


def test_decline_is_unexecuted_and_not_tool_failure(tmp_path):
    store = MoiraiLearning(tmp_path)
    store.record(user_id="u", result=episode(declined=True), goal="inspect")
    attempt = store.episodes("u")[0]["attempts"][0]
    assert attempt["outcome"] == "declined"
    assert not attempt["executed"]
    assert not attempt["used_as_evidence"]


@pytest.mark.asyncio
async def test_distillation_changes_next_task_context_without_hard_routing(tmp_path):
    store = MoiraiLearning(tmp_path)
    store.record(user_id="u", result=episode(), goal="inspect")
    assert await store.consolidate("u", Backend(rule()), min_episodes=1, interval=0) == 1
    restarted = MoiraiLearning(tmp_path)
    recalled = restarted.recall("u", {"required_capabilities": ["test.observe"]})
    assert recalled["rules"][0]["status"] == "hypothesis"
    assert recalled["rules"][0]["revision"] == 1
    assert recalled["recent_outcomes"][0]["outcome"] == "completed"
    assert restarted.recall("u", {"required_capabilities": ["unseen.capability"]})["rules"] == []
    assert restarted.recall("other-user", {"required_capabilities": ["test.observe"]})["rules"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("proposal", [rule(support=["invented"]), rule(capabilities=["invented"]), rule(level="cross_task")])
async def test_unfounded_distillation_never_commits_or_advances_cursor(tmp_path, proposal):
    store = MoiraiLearning(tmp_path)
    store.record(user_id="u", result=episode(), goal="inspect")
    with pytest.raises(ValueError):
        await store.consolidate("u", Backend(proposal), min_episodes=1, interval=0)
    assert store.rules("u") == []
    backend = Backend(rule())
    assert await store.consolidate("u", backend, min_episodes=1, interval=0) == 1
    assert len(backend.batches[0]["episodes"]) == 1


@pytest.mark.asyncio
async def test_error_driven_revision_preserves_history_and_counterexample(tmp_path):
    store = MoiraiLearning(tmp_path)
    store.record(user_id="u", result=episode(), goal="inspect")
    await store.consolidate("u", Backend(rule()), min_episodes=1, interval=0)
    old = store.rules("u")[0]
    failure = episode("run-2", ok=False)
    failure["execution_path"][-1]["procedure_refs"] = [old["reference"]]
    store.record(user_id="u", result=failure, goal="inspect variant")
    revision = rule(rule_id=old["rule_id"], instruction="Check availability before attempting observation; replan if absent.", counterexamples=["run-2"])
    await store.consolidate("u", Backend(revision), min_episodes=1, interval=0)
    latest = store.rules("u")[0]
    assert latest["revision"] == 2
    assert latest["support"] == ["run-1"]
    assert latest["counterexamples"] == ["run-2"]
    assert len(store.export_user_state("u")["rules"]) == 2
    assert store.episodes("u")[1]["adopted_rules"] == [old["reference"]]


@pytest.mark.asyncio
async def test_cross_task_hypothesis_requires_multiple_contexts(tmp_path):
    store = MoiraiLearning(tmp_path)
    store.record(user_id="u", result=episode(), goal="inspect")
    store.record(user_id="u", result=episode("run-2", "other.observe"), goal="another task")
    proposal = rule(level="cross_task", capabilities=[], support=["run-1", "run-2"])
    assert await store.consolidate("u", Backend(proposal), min_episodes=2, interval=0) == 1
    assert store.recall("u", {"required_capabilities": ["new.observe"]})["rules"]


@pytest.mark.asyncio
async def test_interrupted_consolidation_replays_same_batch_after_restart(tmp_path):
    store = MoiraiLearning(tmp_path)
    store.record(user_id="u", result=episode(), goal="inspect")
    entered = asyncio.Event()

    class Waiting:
        async def distill(self, batch):
            entered.set()
            await asyncio.Future()

    store.schedule("u", Waiting(), idle_seconds=0, min_episodes=1, interval=0)
    await asyncio.wait_for(entered.wait(), 2)
    await store.interrupt("u")
    assert store.rules("u") == []
    restarted = MoiraiLearning(tmp_path)
    assert await restarted.consolidate("u", Backend(rule()), min_episodes=1, interval=0) == 1
    await store.stop()


def test_portability_purge_and_training_boundary(tmp_path):
    source = MoiraiLearning(tmp_path / "source")
    source.record(user_id="u", result=episode(), goal="inspect")
    target = MoiraiLearning(tmp_path / "target")
    target.import_user_state("v", source.export_user_state("u"))
    assert target.episodes("v")[0]["id"] == "run-1"
    assert target.episodes("u") == []
    assert target.training_examples("v")[0]["metadata"]["goal_verification"] == "unknown"
    target.purge_user("v")
    assert target.episodes("v") == []


@pytest.mark.asyncio
async def test_conversation_feeds_learning_into_live_capability_observation(tmp_path):
    learning = MoiraiLearning(tmp_path)
    learning.record(user_id="u", result=episode(), goal="inspect")
    await learning.consolidate("u", Backend(rule()), min_episodes=1, interval=0)
    service = ConversationService.__new__(ConversationService)
    service.reasoning_service = SimpleNamespace(template_memory=SimpleNamespace(learning=learning, match_action_template=lambda **_: {}))
    service.capability_service = SimpleNamespace(resolve_capability_intent=AsyncMock(return_value={"candidates": []}))
    projected = await service._resolve_runtime_capabilities({"required_capabilities": ["test.observe"]}, run_context=None, user_config={}, user_id="u")
    assert projected["candidates"] == []
    assert projected["process_experience"]["rules"][0]["instruction"]
    service.capability_service.resolve_capability_intent.assert_awaited_once()

    disabled = await service._resolve_runtime_capabilities(
        {"required_capabilities": ["test.observe"]}, run_context=None,
        user_config={"moirai_learning": {"enabled": False}}, user_id="u",
    )
    assert "process_experience" not in disabled


def test_recall_uses_recent_episodes_and_timestamp_cursor_is_strict(tmp_path, monkeypatch):
    monkeypatch.setattr("agentkit.tools.moirai.learning.time.time", lambda: 100)
    store = MoiraiLearning(tmp_path)
    for i in range(260):
        store.record(user_id="u", result=episode(f"run-{i}", ok=i != 259), goal="inspect")
    recalled = store.recall("u", {"required_capabilities": ["test.observe"]})
    assert recalled["recent_outcomes"][-1]["outcome"] == "failed"
    assert len(store.episodes("u", limit=300, after=100)) == 259


@pytest.mark.asyncio
async def test_concurrent_instances_do_not_commit_stale_distillation(tmp_path):
    first, second = MoiraiLearning(tmp_path), MoiraiLearning(tmp_path)
    first.record(user_id="u", result=episode(), goal="inspect")

    class RacingBackend:
        async def distill(self, batch):
            assert await second.consolidate("u", Backend(rule()), min_episodes=1, interval=0) == 1
            return {"rules": [rule()]}

    assert await first.consolidate("u", RacingBackend(), min_episodes=1, interval=0) == 0
    assert len(first.export_user_state("u")["rules"]) == 1


def test_invalid_archive_rolls_back_all_imported_episodes(tmp_path):
    store = MoiraiLearning(tmp_path)
    payload = {"version": 1, "episodes": [{"id": "new", "attempts": []}],
               "rules": [{**rule(support=["missing"]), "rule_id": "r", "revision": 1}]}
    with pytest.raises(ValueError, match="unknown episodes"):
        store.import_user_state("u", payload)
    assert store.episodes("u") == []


@pytest.mark.asyncio
async def test_direct_tool_attempts_can_form_tool_scoped_experience(tmp_path):
    store = MoiraiLearning(tmp_path)
    direct = episode()
    direct["execution_path"] = direct["execution_path"][1:]
    store.record(user_id="u", result=direct, goal="inspect")
    proposal = rule(capabilities=[], tools=["test.observe"], stages=["Inspect and verify the result."])
    assert await store.consolidate("u", Backend(proposal), min_episodes=1, interval=0) == 1
    assert store.recall("u", {"candidate_names": ["test.observe"]})["rules"][0]["stages"]
    assert store.recall("u", {"candidate_names": ["other.tool"]})["rules"] == []


def test_learning_configuration_uses_existing_nested_env(monkeypatch):
    from config import PrometheaConfig

    monkeypatch.setenv("MOIRAI_LEARNING__ENABLED", "false")
    monkeypatch.setenv("MOIRAI_LEARNING__MIN_EPISODES", "12")
    settings = PrometheaConfig(_env_file=None).moirai_learning
    assert settings.enabled is False
    assert settings.min_episodes == 12
