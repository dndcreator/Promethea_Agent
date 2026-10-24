from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.public_contracts import SemanticUIWrite, SemanticUIFeedback, SemanticSurface, SituationUpdate
from gateway.self_model_service import SelfModelService
from gateway.task_service import TaskExecutionConflict
from gateway.http.routes import semantic_ui
from gateway.http.routes.auth import get_current_user_id
from tests.test_agent_messages import inbox_host
from tests.test_ambient_service import setup, Core, call
from tests.test_background_agents import drain


def command(**values):
    return SemanticUIWrite(**{"expression_id": "reading", "expected_revision": 0, "kind": "choice", "content": "Want a quick comparison?", "choices": [{"id": "compare", "label": "Compare"}, {"id": "later", "label": "Later"}], **values})


def model(tmp_path):
    _, _, conversation, _, manager = inbox_host(tmp_path)
    emitter = EventEmitter()
    return SelfModelService(message_manager=manager, event_emitter=emitter, workspace_root=str(tmp_path)), manager


@pytest.mark.asyncio
async def test_expression_feedback_replays_once_and_cannot_execute_or_write_memory(tmp_path):
    service, _ = model(tmp_path)
    service.memory_service = SimpleNamespace(create_entry=AsyncMock())
    service.capability_service = SimpleNamespace(call_tool=AsyncMock())
    expression = await service.semantic_ui.present("alice", command())
    assert expression["revision"] == 1
    assert await service.semantic_ui.present("alice", command()) == expression
    assert len(service.event_emitter.get_history(EventType.SEMANTIC_UI_UPDATED)) == 1
    feedback = SemanticUIFeedback(expected_revision=1, action="respond", choice_id="compare")
    result = await service.semantic_ui.feedback("alice", "reading", feedback)
    assert result["state"] == "responded" and result["revision"] == 2
    assert await service.semantic_ui.feedback("alice", "reading", feedback) == result
    assert len(service.state.get("alice").feedback) == 1
    assert len(service.event_emitter.get_history(EventType.SEMANTIC_UI_INTERACTED)) == 1
    assert "compare" in str(service.working_context("alice"))
    service.memory_service.create_entry.assert_not_awaited()
    service.capability_service.call_tool.assert_not_awaited()
    closed = await service.semantic_ui.feedback("alice", "reading", SemanticUIFeedback(expected_revision=2, action="dismiss"))
    assert closed["state"] == "dismissed" and closed["response"] == "compare"
    with pytest.raises(TaskExecutionConflict):
        await service.semantic_ui.present("alice", command(content="different"))


@pytest.mark.asyncio
async def test_expressions_are_owned_anchored_revisioned_and_restored(tmp_path):
    service, manager = model(tmp_path)
    manager.add_message("chat", "assistant", "A readable source.", "alice", sync_memory=False)
    source = manager.get_messages("chat", user_id="alice")[0]
    await service.semantic_ui.present("alice", command(session_id="chat", message_id=source["id"]))
    assert service.semantic_ui.view("bob")["expressions"] == []
    with pytest.raises(KeyError):
        await service.semantic_ui.present("bob", command(session_id="chat", message_id=source["id"]))
    with pytest.raises(KeyError):
        await service.semantic_ui.feedback("bob", "reading", SemanticUIFeedback(expected_revision=1, action="dismiss"))
    with pytest.raises(KeyError):
        await service.semantic_ui.present("alice", command(session_id="chat", message_id="missing"))
    with pytest.raises(ValueError):
        await service.semantic_ui.feedback("alice", "reading", SemanticUIFeedback(expected_revision=1, action="respond", choice_id="forged"))
    await service.semantic_ui.observe_surface("alice", SemanticSurface(view="chat", session_id="chat"))
    restored = SelfModelService(message_manager=manager, workspace_root=str(tmp_path))
    assert restored.semantic_ui.view("alice")["expressions"][0]["message_id"] == source["id"]
    assert restored.working_context("alice")["surface"]["view"] == "unknown"
    dismissed = await restored.semantic_ui.feedback("alice", "reading", SemanticUIFeedback(expected_revision=1, action="dismiss"))
    assert dismissed["state"] == "dismissed"
    hidden = command(session_id="chat", message_id=source["id"], hidden=True).model_copy(update={"expected_revision": 2})
    assert (await restored.semantic_ui.present("alice", hidden))["hidden"]


@pytest.mark.asyncio
async def test_cognitive_revision_is_independent_of_ui_and_observation_noise(tmp_path):
    service, _ = model(tmp_path)
    update = SituationUpdate(expected_revision=0, attention=["Finish research"], questions=["Which source is current?"], interpretation="Unverified working view")
    await service.semantic_ui.present("alice", command())
    await service.event_emitter.emit(EventType.ACTION_OBSERVATION_COMMITTED, {"user_id": "alice", "task_id": "t"})
    result = await service.update_situation("alice", update)
    assert result["revision"] == 1
    await service.event_emitter.emit(EventType.GOAL_GAPS_UPDATED, {"user_id": "alice"})
    assert service.working_context("alice")["revision"] == 1
    with pytest.raises(TaskExecutionConflict):
        await service.update_situation("alice", update)
    context = await service.build_context(user_id="alice")
    assert context["global_context"]["identity_source"]
    assert context["situational_context"]["working"]["attention"] == ["Finish research"]
    assert context["situational_context"]["working"]["questions"] == ["Which source is current?"]
    assert service.working_context("bob")["attention"] == []


@pytest.mark.asyncio
async def test_failed_persistence_does_not_fabricate_expression_or_feedback(tmp_path, monkeypatch):
    service, _ = model(tmp_path)
    await service.semantic_ui.present("alice", command())
    before = service.state.get("alice")
    monkeypatch.setattr(service.state, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        await service.semantic_ui.feedback("alice", "reading", SemanticUIFeedback(expected_revision=1, action="dismiss"))
    assert service.state.get("alice") == before


@pytest.mark.asyncio
async def test_personal_transfer_preserves_working_cognition_but_not_visible_surface(tmp_path):
    service, manager = model(tmp_path)
    await service.update_situation("alice", SituationUpdate(expected_revision=0, questions=["Follow up tomorrow"]))
    await service.semantic_ui.present("alice", command())
    await service.semantic_ui.observe_surface("alice", SemanticSurface(view="chat", session_id="chat"))
    target = SelfModelService(message_manager=manager, workspace_root=str(tmp_path / "target"))
    target.state.import_user_state("bob", service.state.export_user_state("alice"))
    assert target.working_context("bob")["questions"] == ["Follow up tomorrow"]
    assert target.working_context("bob")["surface"]["view"] == "unknown"
    assert target.semantic_ui.view("bob")["expressions"][0]["expression_id"] == "reading"
    target.state.purge_user_state("bob")
    assert target.semantic_ui.view("bob")["expressions"] == []


def test_feedback_http_rejects_host_commands_and_stale_choices(tmp_path, monkeypatch):
    service, _ = model(tmp_path)
    monkeypatch.setattr(semantic_ui, "get_gateway_server", lambda: SimpleNamespace(self_model_service=service))
    app = FastAPI()
    app.include_router(semantic_ui.router)
    app.dependency_overrides[get_current_user_id] = lambda: "alice"
    with TestClient(app) as api:
        assert api.get("/semantic-ui").json()["expressions"] == []
        assert api.post("/semantic-ui/missing/feedback", json={"expected_revision": 1, "action": "dismiss"}).status_code == 404
        assert api.post("/semantic-ui/context", json={"session_id": "foreign"}).status_code == 404
        assert api.post("/semantic-ui/reading/feedback", json={"expected_revision": 1, "action": "respond", "choice_id": "compare", "tool_name": "shell.exec"}).status_code == 422
        assert api.post("/semantic-ui/context", json={"view": "chat", "session_id": "chat"}).status_code == 200


@pytest.mark.asyncio
async def test_model_expression_and_user_response_reenter_existing_ambient_loop(tmp_path):
    payload = command().model_dump()
    core = Core(call("semantic_ui.present", **payload))
    _, runtime, conversation, manager, ambient = setup(tmp_path, core)
    # The fixture host has no emitter by default; production injects one shared bus.
    events = EventEmitter()
    conversation.event_emitter = events
    conversation.self_model_service.event_emitter = events
    conversation.self_model_service.semantic_ui.events = events
    events.on(EventType.SEMANTIC_UI_INTERACTED, conversation.self_model_service.observe)
    events.on(EventType.SEMANTIC_UI_INTERACTED, ambient._observe)
    from gateway.public_contracts import AmbientSettings
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await drain(runtime)
        assert conversation.self_model_service.semantic_ui.view("alice")["expressions"]
        assert manager.get_messages("chat", user_id="alice") == []
        await conversation.self_model_service.semantic_ui.feedback("alice", "reading", SemanticUIFeedback(expected_revision=1, action="respond", choice_id="compare"))
        scene = ambient.store.get("alice")
        assert scene.last_trigger["event_type"] == EventType.SEMANTIC_UI_INTERACTED.value
        scene.next_check_at = 0
        ambient.store.put(scene)
        await drain(runtime)
        assert "compare" in str(core.requests[-1])
        assert manager.get_messages("chat", user_id="alice") == []
    finally:
        await runtime.shutdown()


def test_expression_schema_does_not_accept_code_or_invalid_semantics():
    with pytest.raises(ValidationError):
        command().model_copy().model_validate({**command().model_dump(), "script": "fetch('/api/config')"})
    with pytest.raises(ValidationError):
        SemanticUIWrite(expression_id="bad", expected_revision=0, kind="choice", content="No options")


def test_registered_situation_tools_have_concrete_input_contracts(tmp_path):
    from agentkit.tools.standard.situation_tools import create_situation_tools
    service, _ = model(tmp_path)
    tools = {tool.tool_id: tool for tool in create_situation_tools(service)}
    assert len(tools) == 6
    assert all(tool.input_schema["type"] == "object" and tool.input_schema["additionalProperties"] is False for tool in tools.values())
    assert "expected_revision" in tools["cognition.update_situation"].input_schema["required"]
    assert "expression_id" in tools["semantic_ui.present"].input_schema["required"]


@pytest.mark.asyncio
async def test_workspace_archive_round_trip_uses_real_cognitive_state_and_disables_autonomy(tmp_path, monkeypatch):
    from gateway.http.routes import personal
    from gateway.http.project_store import ProjectStore
    from gateway.http.personal_workspace_archive import build_archive, read_archive
    from gateway.ambient_state import AmbientStore

    service, manager = model(tmp_path)
    await service.update_situation("alice", SituationUpdate(expected_revision=0, questions=["Check the release"]))
    await service.semantic_ui.present("alice", command())
    source_control = AmbientStore(tmp_path / "source-control.json", cognition_store=service.state)
    control = source_control.get("alice", "chat")
    control.settings.enabled = True
    source_control.put(control)
    source = SimpleNamespace(message_manager=manager, self_model_service=service, ambient_service=SimpleNamespace(store=source_control))
    monkeypatch.setattr(personal, "get_project_store", lambda: ProjectStore(tmp_path / "projects.sqlite3"))
    monkeypatch.setattr(personal.user_manager, "get_user_config", lambda _user: {})
    monkeypatch.setattr(personal.user_file_store, "export_user_bundle", lambda **_kwargs: {})
    monkeypatch.setattr(personal.user_file_store, "import_user_bundle", lambda **_kwargs: {})
    monkeypatch.setattr(personal.avatar_service, "export_user_bundle", lambda **_kwargs: {})
    monkeypatch.setattr(personal.avatar_service, "import_user_bundle", lambda **_kwargs: {})
    payload = personal._build_workspace_payload(gateway_server=source, user_id="alice")
    _, decoded = read_archive(build_archive(user_id="alice", payload=payload))
    decoded["source_user_id"] = "alice"
    target, target_manager = model(tmp_path / "target")
    target_control = AmbientStore(tmp_path / "target-control.json", cognition_store=target.state)
    destination = SimpleNamespace(message_manager=target_manager, self_model_service=target, ambient_service=SimpleNamespace(store=target_control))
    result = await personal._restore_workspace_payload(gateway_server=destination, config_service=SimpleNamespace(), user_id="bob", payload=decoded, merge=True)
    assert result["applied"]["self_model"]["success"]
    assert target.working_context("bob")["questions"] == ["Check the release"]
    assert target.semantic_ui.view("bob")["expressions"][0]["expression_id"] == "reading"
    assert not target_control.get("bob").settings.enabled
