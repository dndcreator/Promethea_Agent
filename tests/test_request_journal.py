import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.evaluation import Budget, BudgetExceeded, digest, journal_exposure
from tests.support.runtime_efficiency import PairedEndpoint


def make_endpoint(monkeypatch, path, send, cap=0.03):
    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=send))))
    return PairedEndpoint({"PROMETHEA_EVAL_AGENT_MODEL": "fixture", "PROMETHEA_EVAL_AGENT_BASE_URL": "https://example.invalid", "PROMETHEA_EVAL_AGENT_API_KEY": "SECRET-NOT-IN-JOURNAL"},
                          Budget(max_tokens=200000, max_cost_usd=0.5), (0.3, 1.2), journal_path=path, max_request_cost_usd=cap)


def response():
    return SimpleNamespace(id="one", model="fixture", usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 100, "completion_tokens": 50}),
                           choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"action":"answer","content":"ok"}'))])


@pytest.mark.asyncio
async def test_full_request_is_durable_before_transport_and_settles_once(tmp_path, monkeypatch):
    path = tmp_path / "requests.jsonl"

    async def send(**params):
        record = json.loads(path.read_text(encoding="utf-8").strip())
        assert record["state"] == "pending" and record["request"] == params and record["request_hash"] == digest(params)
        assert record["reserved_cost_usd"] <= 0.03
        return response()

    endpoint = make_endpoint(monkeypatch, path, send)
    await endpoint.call_llm([{"role": "user", "content": "hello"}], user_config={"api": {"max_tokens": 8192}})
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["state"] for row in records] == ["pending", "settled"]
    assert "SECRET-NOT-IN-JOURNAL" not in path.read_text(encoding="utf-8")
    assert len(endpoint.receipts) == 1 and endpoint.budget.calls == 1
    assert journal_exposure(path) == {"unresolved_requests": 0, "unknown_reserve_usd": 0}


@pytest.mark.asyncio
async def test_timeout_keeps_only_specific_request_reserve_and_stops(tmp_path, monkeypatch):
    async def send(**_):
        raise TimeoutError("fixture")

    path = tmp_path / "requests.jsonl"
    endpoint = make_endpoint(monkeypatch, path, send)
    with pytest.raises(RuntimeError):
        await endpoint.call_llm([{"role": "user", "content": "hello"}], user_config={"api": {"max_tokens": 8192}})
    exposure = journal_exposure(path)
    assert exposure["unresolved_requests"] == 1 and 0 < exposure["unknown_reserve_usd"] < 0.03
    assert exposure["unknown_reserve_usd"] == endpoint.receipts[0]["reserved_cost_usd"]
    with pytest.raises(BudgetExceeded):
        await endpoint.call_llm([], user_config={"api": {"max_tokens": 8192}})
    assert len(endpoint.receipts) == endpoint.budget.calls == 1


@pytest.mark.asyncio
async def test_journal_failure_prevents_send_and_settlement_failure_keeps_known_receipt(tmp_path, monkeypatch):
    sends = []

    async def send(**params):
        sends.append(params)
        return response()

    endpoint = make_endpoint(monkeypatch, tmp_path / "first.jsonl", send)
    def fail(record):
        raise OSError("disk unavailable")
    monkeypatch.setattr(endpoint, "_journal", fail)
    with pytest.raises(OSError):
        await endpoint.call_llm([])
    assert sends == [] and endpoint.stop_reason and endpoint.budget.usage_known
    endpoint = make_endpoint(monkeypatch, tmp_path / "second.jsonl", send)
    original = endpoint._journal
    def fail_settlement(record):
        if record["state"] == "settled":
            raise OSError("disk unavailable")
        original(record)
    monkeypatch.setattr(endpoint, "_journal", fail_settlement)
    with pytest.raises(OSError):
        await endpoint.call_llm([])
    assert len(sends) == 1 and len(endpoint.receipts) == 1
    assert endpoint.receipts[0]["usage"] and endpoint.budget.usage_known and endpoint.stop_reason


@pytest.mark.asyncio
async def test_single_request_reserve_checks_before_send(tmp_path, monkeypatch):
    async def send(**_):
        raise AssertionError("must not send")
    path = tmp_path / "requests.jsonl"
    endpoint = make_endpoint(monkeypatch, path, send, cap=0.00001)
    with pytest.raises(BudgetExceeded, match="single-request"):
        await endpoint.call_llm([], user_config={"api": {"max_tokens": 8192}})
    assert endpoint.budget.calls == 0 and not path.exists()


def test_journal_with_corrupt_record_is_not_silently_free(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text('{"state":"pending"', encoding="utf-8")
    with pytest.raises(ValueError):
        journal_exposure(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,fields,actions,collections,required", [
    ("simple", 2, 2, 0, 512), ("medium", 5, 1, 0, 3000),
    ("large", 6, 4, 1, 6000), ("underestimated", 2, 2, 0, 6000),
])
async def test_four_budget_categories_exercise_real_state_transitions_without_paid_model(kind, fields, actions, collections, required):
    from gateway.action import ActionService
    from scripts.evaluate_runtime_efficiency import ReplayModel
    from tests.support.task_progress import resolve_output_policy

    corpus = json.loads((Path(__file__).parent / "evaluation/budget-prediction-live.json").read_text(encoding="utf-8"))
    case = {"delivery_contract": {key: [str(n) for n in range(count)] for key, count in [("fields", fields), ("actions", actions), ("persistent_collections", collections)]}}
    for policy in corpus["policies"]:
        effective = resolve_output_policy(policy, case, corpus["prediction"])
        model, writes = ReplayModel({"mode": "output", "required_output": required}), []
        await ActionService(conversation_core=model).run_action(goal="fixture", messages=[], budget=4,
            user_config={"api": {"max_tokens": effective["initial"], "output_token_limit": effective["ceiling"]}},
            tool_executor=lambda name, args: writes.append((name, args)) or {"path": args["path"]})
        assert bool(writes) == (kind != "underestimated" or policy["id"] != "predicted_fixed")
        if kind == "underestimated" and policy["id"] == "predicted_adaptive":
            assert [row["max_tokens"] for row in model.calls] == [2048, 4096, 8192, 8192]
        elif policy["id"] != "predicted_adaptive":
            assert {row["max_tokens"] for row in model.calls} == {effective["initial"]}
