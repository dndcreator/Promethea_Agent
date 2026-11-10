import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.capability_service import CapabilityService
from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.tools.projection import project_capability_snapshot, registry_revision, resolve_capability_candidates, project_tool_directory


def row(name, **fields):
    return {
        "service_name": "test", "tool_name": name, "description": name,
        "callable_now": True, "callable_reason": "callable", "schema_status": "declared",
        "input_schema": {"type": "object"}, "side_effect_level": "read_only",
        "required_capability": "computer.screen", "provides": ["computer.screen"], **fields,
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
    assert out["selected_specs"] == []
    assert [item["name"] for item in project_capability_snapshot(catalog, preferred_tools=["test.observe", "test.missing"])["selected_specs"]] == ["test.observe"]
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
        row("unrelated", required_capability="computer.screensaver", provides=["computer.screensaver"]),
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


def test_dependencies_do_not_claim_provided_capabilities_and_identity_still_resolves():
    catalog = [row("needs_screen", provides=[])]
    result = resolve_capability_candidates(catalog, request={}, required={"computer.screen"}, max_effect="read_only")
    assert not result["candidates"]
    assert result["unmatched_capabilities"] == ["computer.screen"]
    result = resolve_capability_candidates(catalog, request={}, required={"test.needs_screen"}, max_effect="read_only")
    assert result["candidates"][0]["name"] == "test.needs_screen"


def test_missing_direct_match_preserves_general_discovery_without_faking_coverage():
    catalog = [row("author", provides=["software.tools.create"], required_capability=None, side_effect_level="workspace_write")]
    original = deepcopy(catalog)
    result = resolve_capability_candidates(catalog, request={}, required={"remote.repository.write"}, max_effect="read_only")
    assert result["candidate_count"] == 0 and result["task_feasibility"] == "not_assessed"
    assert result["resolution_scope"] == "registered_declarations_only"
    assert result["available_capability_groups"]["software"] == 1
    assert result["coverage"]["remote.repository.write"] == {"declared": 0, "callable_within_scope": 0}
    assert catalog == original


def test_capability_coverage_distinguishes_disabled_and_effect_scope_from_missing():
    catalog = [row("disabled", provides=["software.tools.create"], callable_now=False, callable_reason="disabled"),
               row("write", provides=["document.write"], side_effect_level="external_write")]
    result = resolve_capability_candidates(catalog, request={}, required={"software.tools.create", "document.write", "missing"}, max_effect="read_only")
    assert result["unmatched_capabilities"] == ["missing"]
    assert result["unavailable_capabilities"] == ["document.write", "software.tools.create"]
    assert "software" not in result["available_capability_groups"]


def test_schema_budget_never_drops_candidate_identities_or_mutates_declarations():
    catalog = [row(str(i), input_schema={"type": "object", "description": "x" * 8000}) for i in range(8)]
    original = deepcopy(catalog)
    result = resolve_capability_candidates(catalog, request={}, required={"computer.screen"}, max_effect="read_only", schema_budget_chars=0)
    assert len(result["candidates"]) == 8 and catalog == original
    assert all(row["schema_status"] == "inspect_required" and row["input_schema"] == {} for row in result["candidates"])
    assert all(row["schema_inspection"]["capability_names"] == [row["name"]] for row in result["candidates"])
    assert result["coverage"]["computer.screen"]["callable_within_scope"] == 8


def test_discovery_groups_preserve_identifiers_without_copying_runtime_definitions():
    catalog = [row("visible", description="DO-NOT-INJECT", input_schema={"description": "LARGE-SCHEMA"}),
               row("disabled", callable_now=False)]
    snapshot = project_capability_snapshot(catalog)
    directory = project_tool_directory(snapshot["compact_index"])
    assert directory == [{"namespace": "test", "available": ["test.visible"],
                          "unavailable": ["test.disabled"], "provides": ["computer.screen"]}]
    assert "DO-NOT-INJECT" not in str(directory) and "LARGE-SCHEMA" not in str(directory)
    assert snapshot["compact_index"][0]["description"] == "DO-NOT-INJECT"
    assert snapshot["selected_specs"] == []


def test_explicit_schema_selection_never_includes_unavailable_tools():
    catalog = [row("offline", callable_now=False), row("ready")]
    out = project_capability_snapshot(catalog, preferred_tools=["test.offline", "test.ready"])
    assert [item["name"] for item in out["selected_specs"]] == ["test.ready"]


def test_wildcard_discovery_uses_existing_resolution_and_keeps_effect_scope():
    catalog = [row("read"), row("write", side_effect_level="external_write"), row("offline", callable_now=False)]
    out = resolve_capability_candidates(catalog, request={}, required={"*"}, max_effect="read_only")
    assert [item["name"] for item in out["candidates"]] == ["test.read"]
    assert out["coverage"]["*"] == {"declared": 3, "callable_within_scope": 1}
    assert out["unavailable_candidates"][0]["tool_name"] == "offline"
    assert out["task_feasibility"] == "not_assessed"
    assert out["directory"][0]["available"] == ["test.read", "test.write"]
    assert out["directory"][0]["unavailable"] == ["test.offline"]


@pytest.mark.asyncio
async def test_wildcard_directory_never_exposes_another_owners_private_tool():
    service = CapabilityService(mcp_manager=SimpleNamespace(get_available_services_filtered=lambda: {"mcp_services": []}))
    service._tool_discovery_initialized = True
    service.register_tool(SimpleNamespace(tool_id="private.echo", name="private.echo", description="Private tool",
        input_schema={"type": "object"}, side_effect_level="read_only", owner_user_id="alice", invoke=AsyncMock()))
    intent = {"objective": "Discover", "required_capabilities": ["*"], "max_side_effect": "read_only"}
    own = await service.resolve_capability_intent(intent, run_context=SimpleNamespace(user_id="alice"))
    other = await service.resolve_capability_intent(intent, run_context=SimpleNamespace(user_id="bob"))
    assert "private.echo" in json.dumps(own["directory"])
    assert "private.echo" not in json.dumps(other)
