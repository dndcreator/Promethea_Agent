"""Isolated real Runtime composition; only external model/MCP/config inputs vary."""
from copy import deepcopy
import json
from types import SimpleNamespace

from agentkit.tools.standard.workspace_tools import WorkspaceReadFileTool, WorkspaceWriteFileTool
from config import PrometheaConfig
from gateway.capability_service import CapabilityService
from gateway.conversation_service import ConversationService
from gateway.events import EventEmitter
from gateway.http.message_manager import MessageManager
from gateway.http.session_store import SessionStorage
from gateway.runtime_event_log import RuntimeEventLog
from gateway.self_model_service import SelfModelService
from gateway.server import GatewayServer
from gateway.task_service import TaskService
from gateway.workflow_engine import WorkflowEngine
from gateway.workspace_service import WorkspaceService


class ScriptedModel:
    """A model boundary, not a replacement for Conversation/Action/Capability."""
    def __init__(self, actions):
        self.actions = iter(actions)
        self.calls = []

    async def call_llm(self, messages, **kwargs):
        self.calls.append(deepcopy(messages))
        action = next(self.actions)
        if callable(action):
            action = action(messages)
        return {"status": "success", "content": json.dumps(action), "usage": {"prompt_tokens": 0, "completion_tokens": 0}}

    async def call_llm_stream(self, messages, **kwargs):
        response = await self.call_llm(messages, **kwargs)
        for start in range(0, len(response["content"]), 16):
            yield response["content"][start:start + 16]


def finish_from_observation(messages):
    for row in reversed(messages):
        if isinstance(row.get("content"), list):
            fact = json.loads(row["content"][0]["text"])
            return {"action": "answer", "content": "Observed result: " + json.dumps(fact["result"] if fact["status"] == "completed" else fact["error"], ensure_ascii=False), "evidence_refs": [fact["observation_id"]]}
    raise AssertionError("A completion needs a real tool Observation")


def runtime_at(root, model):
    settings = PrometheaConfig(_env_file=None).model_dump()
    settings["memory"]["enabled"] = False
    settings["memory"]["embedding"]["provider"] = "disabled"
    settings["org_brain"]["enabled"] = False
    settings["self_evolve"]["enabled"] = False
    config = SimpleNamespace(get_merged_config=lambda _: deepcopy(settings))
    manager = MessageManager.__new__(MessageManager)
    manager.session_store = SessionStorage(str(root / "sessions.json"))
    manager.session = manager.session_store.load_all()
    manager.memory_adapter = None
    manager.max_messages_per_session = 100
    manager.max_history_rounds = 50
    emitter = EventEmitter(RuntimeEventLog(storage_path=str(root / "events.jsonl")))
    workspace = WorkspaceService(base_dir=str(root / "workspaces"), event_emitter=emitter)
    tasks = TaskService(storage_path=str(root / "tasks.json"), event_emitter=emitter)
    workflow = WorkflowEngine(storage_path=str(root / "workflows.json"), task_service=tasks, workspace_service=workspace, event_emitter=emitter)
    mcp = SimpleNamespace(get_available_services_filtered=lambda: {"mcp_services": []})
    capabilities = CapabilityService(workspace_service=workspace, event_emitter=emitter, mcp_manager=mcp)
    self_model = SelfModelService(workspace_root=str(root), task_service=tasks, message_manager=manager, capability_service=capabilities)
    conversation = ConversationService(conversation_core=model, capability_service=capabilities,
                                       message_manager=manager, config_service=config, event_emitter=emitter,
                                       workflow_engine=workflow, self_model_service=self_model)
    conversation.action_service.task_service = tasks
    server = GatewayServer(event_emitter=emitter)
    server.message_manager, server.workspace_service = manager, workspace
    server.task_service, server.workflow_engine = tasks, workflow
    server.capability_service, server.conversation_service = capabilities, conversation
    server.config_service, server.mcp_manager = config, mcp
    server.self_model_service = self_model
    server.ensure_capability_service()
    # The test's external tool catalog is closed, not the user's extension directory.
    capabilities._tool_discovery_initialized = True
    for tool in (WorkspaceReadFileTool(workspace_service=workspace), WorkspaceWriteFileTool(workspace_service=workspace)):
        capabilities.register_tool(tool)
    return server
