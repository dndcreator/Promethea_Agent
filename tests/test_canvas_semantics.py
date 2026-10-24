import hashlib

import pytest

from computer.canvas_components import render_component_document
from computer.canvas_semantics import snapshot, interact
from computer.environment import EnvironmentController
from gateway.public_contracts import CanvasSemanticSnapshot
from tests.test_canvas_components import document


def act(source, state, component, operation="activate", **kwargs):
    return interact(source, state, component_id=component, operation=operation, definition_revision=hashlib.sha256(source.encode()).hexdigest(), **kwargs)


def test_semantics_use_real_app_values_and_explicit_declaration_provenance():
    value = document()
    value["root"]["children"][1]["children"][0].update(description="Unit price", object_ref={"kind": "product", "id": "sku1"})
    source = render_component_document(value)
    result = CanvasSemanticSnapshot.model_validate(snapshot(source, {"revision": 4, "value": {"quantity": 7}}))
    assert result.status == "compiled" and result.revision == 4
    fields = {item.component_id: item for item in result.components}
    assert fields["quantity"].value == 7
    assert fields["quantity"].parent_id == "fields"
    assert fields["price"].object_ref.id == "sku1"
    assert fields["price"].input_schema == {"type": "number"}
    assert fields["mode"].input_schema["enum"] == ["train", "bus"]
    assert fields["calculate"].operations == ["activate"]
    assert "not_external_business_facts" in result.state_origin
    assert snapshot(source + "<!-- custom script not verified -->", {})["status"] == "declared"
    assert snapshot("<h1>No contract</h1>", {})["status"] == "undeclared"
    with pytest.raises(ValueError, match="exactly one"):
        snapshot(source + source, {})


def test_runtime_interprets_existing_dsl_without_model_or_arbitrary_code():
    value = document()
    value["root"]["children"].extend([
        {"type": "button", "id": "more", "label": "More", "actions": [{"op": "increment", "field": "quantity", "value": 1}, {"op": "toggle", "field": "done"}]},
        {"type": "button", "id": "clear", "label": "Clear", "actions": [{"op": "reset"}]},
        {"type": "button", "id": "rename", "label": "Rename", "actions": [{"op": "set", "field": "note", "value": "Updated"}]},
    ])
    source = render_component_document(value)
    state = {"value": act(source, {}, "quantity", "set", value=3)}
    assert act(source, state, "calculate")["total"] == 37.5
    changed = act(source, state, "more")
    assert changed["quantity"] == 4 and changed["done"] is True
    assert act(source, {"value": changed}, "clear") == value["initial_state"]
    assert act(source, {}, "rename")["note"] == "Updated"
    for component, operation, new_value in [("quantity", "set", True), ("mode", "set", "plane"), ("title", "activate", None), ("calculate", "set", 2)]:
        with pytest.raises(ValueError):
            act(source, {}, component, operation, value=new_value)
    with pytest.raises(ValueError, match="definition changed"):
        interact(source, {}, component_id="calculate", operation="activate", definition_revision="0" * 64)
    with pytest.raises(ValueError, match="declared fields"):
        snapshot(source, {"value": {"unknown": "not a declared field"}})


@pytest.mark.asyncio
async def test_interaction_uses_state_and_definition_fences_and_publishes_only_committed_changes(tmp_path, monkeypatch):
    source = render_component_document(document())
    (tmp_path / "index.html").write_text(source, encoding="utf-8")
    controller = EnvironmentController(str(tmp_path))
    await controller.initialize()
    registered = await controller.execute("register", {"name": "Budget"})
    identity = registered.result["environment_id"]
    semantics = (await controller.execute("semantics", {"environment_id": identity})).result
    params = {"environment_id": identity, "component_id": "quantity", "operation": "set", "value": 5, "expected_revision": 0, "definition_revision": semantics["definition_revision"]}
    saved = await controller.execute("interact", params)
    assert saved.success and saved.result["value"]["quantity"] == 5
    assert any(event["action"] == "app_state_changed" and "quantity" in event["changed_fields"] for event in saved.metadata["lifecycle_events"])
    stale = await controller.execute("interact", params)
    assert not stale.success and not stale.metadata["lifecycle_events"]
    (tmp_path / "index.html").write_text(source + "\n", encoding="utf-8")
    changed_definition = await controller.execute("interact", {**params, "expected_revision": 1})
    assert not changed_definition.success and "definition changed" in changed_definition.error
    monkeypatch.setattr(controller, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    failed = await controller.execute("state_set", {"environment_id": identity, "expected_revision": 1, "value": {"quantity": 8}})
    assert not failed.success and not failed.metadata["lifecycle_events"]
    assert (await controller.execute("state_get", {"environment_id": identity})).result == saved.result
    restored = EnvironmentController(str(tmp_path))
    await restored.initialize()
    assert (await restored.execute("state_get", {"environment_id": identity})).result == saved.result
