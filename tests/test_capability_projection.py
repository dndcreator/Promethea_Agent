import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.capability_service import CapabilityService
from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.tools.projection import project_capability_snapshot, registry_revision, resolve_capability_candidates


def row(name, **fields):
    return {
        "service_name": "test", "tool_name": name, "description": name,
        "callable_now": True, "callable_reason": "callable", "schema_status": "declared",
        "input_schema": {"type": "object"}, "side_effect_level": "read_only",
        "required_capability": "computer.screen", **fields,
    }


def test_snapshot_projection_is_deterministic_without_runtime_identity():
    catalog = [row("observe"), row("missing", input_schema={}, schema_status="missing", callable_now=False)]
    original = deepcopy(catalog)
    out = project_capability_snapshot(catalog)
    assert out == project_capability_snapshot(catalog)
    assert catalog == original
    assert "snapshot_id" not in out and "generated_at" not in out
    assert out["total_count"] == 2 and out["callable_count"] == 1 and out["missing_schema_count"] == 1
    assert [item["name"] for item in out["compact_index"]] == ["test.observe", "test.missing"]
    assert [item["name"] for item in out["selected_specs"]] == ["test.observe"]
    assert project_capability_snapshot(catalog, schema_budget_chars=0)["selected_specs"] == []


def test_schema_budget_prioritizes_preferred_without_losing_index():
    catalog = [row("alpha"), row("beta")]
    full = project_capability_snapshot(catalog, preferred_tools=["test.beta"])
    budget = len(json.dumps(full["selected_specs"][0], ensure_ascii=False, separators=(",", ":")))
    out = project_capability_snapshot(catalog, preferred_tools=["test.beta"], schema_budget_chars=budget)
    assert out["total_count"] == 2
    assert [item["name"] for item in out["selected_specs"]] == ["test.beta"]
    assert out["schema_budget_chars"] == budget


def test_registry_revision_uses_full_catalog_and_stable_key_order():
    catalog = [row("observe")]
    assert registry_revision(catalog) == registry_revision([dict(reversed(list(catalog[0].items())))])
    changed = deepcopy(catalog)
    changed[0]["input_schema"]["properties"] = {"value": {"type": "string"}}
    assert registry_revision(catalog) != registry_revision(changed)
    changed = [row("observe", callable_now=False, callable_reason="offline")]
    assert registry_revision(catalog) != registry_revision(changed)


def test_candidate_ranking_preserves_unavailable_and_argument_dependent_effects():
    catalog = [
        row("observe"),
        row("control", side_effect_level="privileged_host_action", requires_confirmation=True,
            side_effect_selector={"groups": {"read_only": ["screenshot"]}}),
        row("offline", callable_now=False, callable_reason="offline"),
        row("command", side_effect_level="privileged_host_action"),
        row("unrelated", required_capability="computer.screensaver"),
    ]
    original = deepcopy(catalog)
    out = resolve_capability_candidates(
        catalog, request={"objective": "observe", "preferred_modalities": ["image"]},
        required={"computer.screen"}, max_effect="read_only", preferred_tools=["test.control"],
    )
    assert catalog == original
    assert [item["name"] for item in out["candidates"]] == ["test.control", "test.observe"]
    assert out["candidates"][0]["requires_confirmation"] is True
    assert out["candidates"][0]["confirmation_depends_on_arguments"] is True
    assert out["unavailable_candidates"][0]["tool_name"] == "offline"
    assert out["preferred_modalities"] == ["image"]
    assert out["registry_revision"] == registry_revision(catalog)


@pytest.mark.asyncio
async def test_service_owns_snapshot_identity_reuse_and_event_lifecycle():
    emitter = EventEmitter()
    service = CapabilityService(event_emitter=emitter)
    catalog = [row("observe")]
    service.get_tool_catalog = AsyncMock(return_value=catalog)
    context = SimpleNamespace(user_id="u1", session_id="s1")

    first = await service.build_capability_snapshot(run_context=context)
    second = await service.build_capability_snapshot(run_context=context)
    assert first == second == context.tool_availability
    assert first["snapshot_id"].startswith("caps_") and first["generated_at"].endswith("Z")
    assert len(emitter.get_history()) == 1

    third = await service.build_capability_snapshot(run_context=context, schema_budget_chars=0)
    assert third["snapshot_id"] != first["snapshot_id"]
    assert third["selected_specs"] == []
    catalog[0] = row("observe", callable_now=False, callable_reason="offline")
    fourth = await service.build_capability_snapshot(run_context=context, schema_budget_chars=0)
    assert fourth["registry_revision"] != third["registry_revision"]
    history = emitter.get_history()
    assert len(history) == 3
    assert all(event.event == EventType.CAPABILITY_SNAPSHOT_CREATED for event in history)
    assert history[-1].payload["snapshot_id"] == fourth["snapshot_id"]
    assert history[-1].payload["user_id"] == "u1"


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", [{}, {"required_capabilities": ["computer.screen"], "max_side_effect": "invalid"}])
async def test_invalid_intent_does_not_scan_or_query_runtime(intent):
    service = CapabilityService()
    service.get_tool_catalog = AsyncMock()
    assert "error" in await service.resolve_capability_intent(intent)
    service.get_tool_catalog.assert_not_called()
