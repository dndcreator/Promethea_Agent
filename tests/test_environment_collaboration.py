import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from computer.canvas_components import CanvasResourceRef, render_component_document
from computer.environment import EnvironmentController
from computer.execution_context import bind_workspace
from computer.runtime import ComputerRuntime
from gateway.capability_service import CapabilityService
from gateway.environment_context import EnvironmentViews
from gateway.events import EventEmitter
from gateway.http.user_file_store import UserFileStore
from gateway.protocol import EventType
from gateway.public_contracts import SemanticSurface, SemanticUIFeedback
from gateway.self_model_service import SelfModelService
from gateway.task_service import TaskExecutionConflict
from gateway.workspace_service import WorkspaceService
from tests.test_canvas_components import document
from tests.test_semantic_ui import command


@asynccontextmanager
async def collaboration(tmp_path):
    workspaces = WorkspaceService(base_dir=str(tmp_path / "workspaces"))
    handle = workspaces.resolve_workspace_handle(user_id="alice", workspace_id="ws")
    path = Path(handle.root_path) / "index.html"
    value = document()
    value["root"]["children"][1]["children"][1]["description"] = "Number of travellers, not the price"
    path.write_text(render_component_document(value), encoding="utf-8")
    runtime = ComputerRuntime({"environment": EnvironmentController})
    events = EventEmitter()
    capabilities = CapabilityService(workspace_service=workspaces, computer_runtime=runtime, event_emitter=events)
    model = SelfModelService(capability_service=capabilities, event_emitter=events, workspace_root=str(tmp_path))
    model.environment_sources.file_store = UserFileStore(str(tmp_path / "users"))
    try:
        with bind_workspace(handle):
            registered = await capabilities.execute_computer_action("environment", "register", {"name": "Budget"})
        ref = CanvasResourceRef(kind="canvas", id=registered.result["environment_id"], workspace_id="ws")
        yield model, ref, path, value
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_canvas_feedback_is_persistent_idempotent_and_not_an_app_action(tmp_path):
    async with collaboration(tmp_path) as (model, ref, _, _):
        source = await model.environment_sources.inspect("alice", ref)
        anchor = {"resource": ref.model_dump(), "component_id": "quantity", "definition_revision": source["semantics"]["definition_revision"]}
        item = command(canvas_anchor=anchor)
        await model.semantic_ui.present("alice", item)
        assert await model.semantic_ui.present("alice", item) == model.semantic_ui.view("alice")["expressions"][0]
        feedback = SemanticUIFeedback(expected_revision=1, action="respond", choice_id="later")
        saved = await model.semantic_ui.feedback("alice", "reading", feedback)
        assert saved["response"] == "later"
        assert await model.semantic_ui.feedback("alice", "reading", feedback) == saved
        observed = model.event_emitter.get_history(EventType.SEMANTIC_UI_INTERACTED)
        assert len(observed) == 1 and observed[0].payload["canvas_anchor"] == anchor
        assert (await model.environment_sources.inspect("alice", ref))["semantics"]["revision"] == 0
        restored = SelfModelService(workspace_root=str(tmp_path))
        assert restored.semantic_ui.view("alice")["expressions"][0] == saved
        assert restored.semantic_ui.view("bob")["expressions"] == []
        assert model.state.get("alice").feedback[-1]["canvas_anchor"] == anchor


@pytest.mark.asyncio
async def test_canvas_anchor_ownership_component_and_definition_are_enforced(tmp_path):
    async with collaboration(tmp_path) as (model, ref, path, value):
        source = await model.environment_sources.inspect("alice", ref)
        anchor = {"resource": ref.model_dump(), "component_id": "quantity", "definition_revision": source["semantics"]["definition_revision"]}
        with pytest.raises(KeyError):
            await model.semantic_ui.present("bob", command(canvas_anchor=anchor))
        with pytest.raises(KeyError):
            await model.semantic_ui.present("alice", command(canvas_anchor={**anchor, "component_id": "missing"}))
        with pytest.raises(TaskExecutionConflict):
            await model.semantic_ui.present("alice", command(canvas_anchor={**anchor, "definition_revision": "0" * 64}))
        await model.semantic_ui.present("alice", command(canvas_anchor=anchor))
        value["title"] = "Changed definition"
        path.write_text(render_component_document(value), encoding="utf-8")
        with pytest.raises(TaskExecutionConflict):
            await model.semantic_ui.feedback("alice", "reading", SemanticUIFeedback(expected_revision=1, action="respond", choice_id="compare"))
        assert not model.state.get("alice").feedback
        # A stale expression may still be dismissed, never used as authorization.
        assert (await model.semantic_ui.feedback("alice", "reading", SemanticUIFeedback(expected_revision=1, action="dismiss")))["state"] == "dismissed"


@pytest.mark.asyncio
async def test_focused_component_description_and_file_content_reach_observation(tmp_path, monkeypatch):
    async with collaboration(tmp_path) as (model, ref, path, value):
        store = model.environment_sources.file_store
        entry = store.save_upload(user_id="alice", filename="brief.md", content="Revenue is uncertain.\nDiscuss assumptions first.".encode())
        component = value["root"]["children"][1]["children"][1]
        component["object_ref"] = {"kind": "file", "id": entry["file_id"]}
        path.write_text(render_component_document(value), encoding="utf-8")
        source = await model.environment_sources.inspect("alice", ref)
        surface = SemanticSurface(view="canvas", objects=[ref], active_component_id="quantity", definition_revision=source["semantics"]["definition_revision"])
        assert await model.environment.observe("alice", surface)
        snapshot = await model.environment.snapshot("alice")
        prompt = EnvironmentViews.prompt(snapshot)
        parsed = json.loads(prompt.split("\n", 1)[1])
        selected = parsed["objects"][0]["semantics"]["components"][0]
        assert selected["component_id"] == "quantity" and "travellers" in selected["description"]
        assert selected["object_ref"]["id"] == entry["file_id"]
        details = await model.environment_sources.inspect("alice", ref, component_id="quantity")
        assert "assumptions" in details["related_object"]["content"]["text"]
        def unavailable(**_):
            raise OSError("related file is offline")
        with monkeypatch.context() as patch:
            patch.setattr(store, "get_file", unavailable)
            partial = await model.environment_sources.inspect("alice", ref, component_id="quantity")
            assert partial["semantics"]["components"][0]["component_id"] == "quantity"
            assert partial["related_object"]["status"] == "unavailable"
            # An expression needs its component definition, not the related file's content.
            assert (await model.semantic_ui.present("alice", command(canvas_anchor={"resource": ref.model_dump(), "component_id": "quantity", "definition_revision": source["semantics"]["definition_revision"]})))["revision"] == 1
        value["title"] = "Different page"
        path.write_text(render_component_document(value), encoding="utf-8")
        stale = await model.environment.snapshot("alice")
        assert stale["surfaces"][0]["active_component_id"] is None
        with pytest.raises(ValueError, match="unknown or changed"):
            await model.environment.observe("alice", surface)


@pytest.mark.asyncio
async def test_uploaded_file_content_is_paginated_owned_and_not_inferred_for_images(tmp_path):
    async with collaboration(tmp_path) as (model, _, _, _):
        store = model.environment_sources.file_store
        text = "Read the actual brief, not its filename. " * 200
        entry = store.save_upload(user_id="alice", filename="brief.txt", content=text.encode())
        ref = CanvasResourceRef(kind="file", id=entry["file_id"])
        first = await model.environment_sources.inspect("alice", ref, limit=37)
        assert first["content"]["text"] == text[:37] and first["content"]["next_offset"] == 37
        second = await model.environment_sources.inspect("alice", ref, offset=37, limit=37)
        assert second["content"]["text"] == text[37:74]
        with pytest.raises(KeyError):
            await model.environment_sources.inspect("bob", ref)
        with pytest.raises(ValueError):
            await model.environment_sources.inspect("alice", ref, limit=12001)
        await model.environment.observe("alice", SemanticSurface(view="files", objects=[ref]))
        projection = EnvironmentViews.prompt(await model.environment.snapshot("alice"))
        assert "Read the actual brief" in projection and len(projection) <= 3200
        assert json.loads(projection.split("\n", 1)[1])["objects"][0]["content"]["truncated"]
        # Unavailable extraction is not replaced by a guess from a filename.
        store._decode_to_text = lambda **_: ""
        image = store.save_upload(user_id="alice", filename="sales.png", content=b"test-image")
        unknown = await model.environment_sources.inspect("alice", CanvasResourceRef(kind="file", id=image["file_id"]))
        assert unknown["content"]["status"] == "unavailable" and unknown["content"]["text"] == ""


@pytest.mark.asyncio
async def test_artifact_reads_reuse_workspace_scope_and_leave_binary_unknown(tmp_path):
    async with collaboration(tmp_path) as (model, _, path, _):
        draft = path.parent / "draft.md"
        draft.write_text("Version one: verify before publishing.", encoding="utf-8")
        ref = CanvasResourceRef(kind="artifact", id="draft.md", workspace_id="ws")
        before = await model.environment_sources.inspect("alice", ref, limit=12)
        assert before["content"]["text"] == "Version one:"
        draft.write_text("Version two: revise the assumptions.", encoding="utf-8")
        assert (await model.environment_sources.inspect("alice", ref))["version"] != before["version"]
        with pytest.raises((KeyError, ValueError)):
            await model.environment_sources.inspect("alice", ref.model_copy(update={"id": "../outside.md"}))
        with pytest.raises(KeyError):
            await model.environment_sources.inspect("bob", ref)
        (path.parent / "chart.bin").write_bytes(b"\x00\xff")
        binary = await model.environment_sources.inspect("alice", ref.model_copy(update={"id": "chart.bin"}))
        assert binary["content"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_canvas_feedback_and_file_content_reenter_actual_action_and_ambient_chain(tmp_path):
    from gateway.public_contracts import AmbientSettings
    from tests.test_ambient_service import Core, call, setup
    from tests.test_background_agents import drain

    async with collaboration(tmp_path / "sources") as (owner, ref, _, _):
        core = Core()
        _, runtime, conversation, manager, ambient = setup(tmp_path / "agent", core)
        model = conversation.self_model_service
        model.environment_sources = owner.environment_sources
        model.environment.resolve = model.environment_sources.inspect
        model.semantic_ui.sources = model.environment_sources
        events = EventEmitter()
        conversation.event_emitter = conversation.action_service.event_emitter = events
        model.event_emitter = model.semantic_ui.events = events
        events.on(EventType.SEMANTIC_UI_INTERACTED, model.observe)
        events.on(EventType.SEMANTIC_UI_INTERACTED, ambient._observe)
        entry = owner.environment_sources.file_store.save_upload(user_id="alice", filename="brief.txt", content=b"The release must retain all user drafts.")
        source = await owner.environment_sources.inspect("alice", ref)
        anchor = {"resource": ref.model_dump(), "component_id": "quantity", "definition_revision": source["semantics"]["definition_revision"]}
        core.actions = [call("semantic_ui.present", **command(canvas_anchor=anchor).model_dump())]
        try:
            await model.environment.observe("alice", SemanticSurface(view="canvas", objects=[ref, {"kind": "file", "id": entry["file_id"]}]))
            ambient.configure("alice", "chat", AmbientSettings(enabled=True))
            await drain(runtime)
            assert any("The release must retain all user drafts" in str(request) for request in core.requests)
            assert model.semantic_ui.view("alice")["expressions"][0]["canvas_anchor"] == anchor
            assert not manager.get_messages("chat", user_id="alice")
            reply = SemanticUIFeedback(expected_revision=1, action="respond", choice_id="later")
            await model.semantic_ui.feedback("alice", "reading", reply)
            await model.semantic_ui.feedback("alice", "reading", reply)
            scene = ambient.store.get("alice")
            assert scene.last_trigger["event_type"] == EventType.SEMANTIC_UI_INTERACTED.value
            scene.next_check_at = 0
            ambient.store.put(scene)
            await drain(runtime)
            assert "later" in str(core.requests[-1]) and ref.id in str(core.requests[-1])
            assert len(events.get_history(EventType.SEMANTIC_UI_INTERACTED)) == 1
            recorded = events.get_history(EventType.MODEL_CALL_RECORDED)
            assert any("The release must retain all user drafts" in str(event.payload["request_messages"]) for event in recorded)
            assert not manager.get_messages("chat", user_id="alice")
        finally:
            await runtime.shutdown()


@pytest.mark.asyncio
async def test_proactive_observation_scope_never_grants_app_write_or_child_workspace_access(tmp_path):
    from gateway.ambient_state import AmbientExecution, bind_ambient
    from gateway.capability_service import ToolPolicyViolationError
    from gateway.delegation import DelegationScope, _Budget, bind_delegation
    from gateway.public_contracts import EnvironmentInteraction

    async with collaboration(tmp_path) as (model, ref, _, _):
        await model.environment.observe("alice", SemanticSurface(view="canvas", objects=[ref]))
        granted = model.environment.visible_workspaces("alice")
        assert granted == frozenset({"ws"})
        scope = DelegationScope(_Budget(), workspace_id="delivery", observation_workspaces=granted)
        with bind_ambient(AmbientExecution(None, None, 0)), bind_delegation(scope):
            projection = await model.environment_sources.inspect("alice", ref)
            anchor = {"resource": ref.model_dump(), "component_id": "quantity", "definition_revision": projection["semantics"]["definition_revision"]}
            assert (await model.semantic_ui.present("alice", command(canvas_anchor=anchor)))["revision"] == 1
            with pytest.raises(ToolPolicyViolationError):
                await model.environment_sources.interact("alice", EnvironmentInteraction(resource=ref, interaction={"component_id": "quantity", "operation": "set", "value": 99, "expected_revision": 0, "definition_revision": anchor["definition_revision"]}))
            with pytest.raises(ToolPolicyViolationError):
                with model.capability_service._workspace_scope({"workspace_id": "ws"}, {"user_id": "alice"}):
                    pytest.fail("ordinary execution must not inherit observation permission")
        with bind_delegation(DelegationScope(_Budget(), depth=1, workspace_id="delivery", observation_workspaces=granted)):
            with pytest.raises(ToolPolicyViolationError):
                await model.environment_sources.inspect("alice", ref)
        await model.environment.observe("alice", SemanticSurface(view="canvas", sequence=2, objects=[ref], visible=False))
        assert model.environment.visible_workspaces("alice") == frozenset()
        assert model.environment.visible_workspaces("bob") == frozenset()
