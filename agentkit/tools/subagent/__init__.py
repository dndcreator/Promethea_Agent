"""Optional delegation through the same manifest factory used by other tools."""
from typing import Any

from gateway.delegation import DelegationRequest
from gateway.background_agents import AgentControlRequest
from gateway.agent_messages import AgentReportRequest


class DelegateTool:
    tool_id = name = "subagent.delegate"
    description = (
        "Delegate a bounded, independent objective to a fresh agent using the same Runtime. "
        "Supply all necessary context in objective; parent conversation is not copied. "
        "Background execution is the default: a durable child id returns immediately; use subagent.control to query or send follow-ups. "
        "Set run_in_background=false to collect a one-shot result. Use a tool_calls batch for independent parallel work. "
        "Children cannot request approval or escalate permissions; handle their blockers in the parent."
    )
    input_schema = DelegationRequest.model_json_schema()
    side_effect_level = "workspace_write"
    concurrency_safe = True
    requires_run_option = "multi_agent"
    timeout_ms = 610000
    presentation = {
        "title_i18n": {"zh": "委派子任务", "en": "Delegate subtask"},
        "subject_arg": "label",
    }

    def __init__(self, gateway: Any):
        self.gateway = gateway

    def present_result(self, args, result):
        if not isinstance(result, dict):
            return {}
        presentation = {"summary": str(result.get("output") or result.get("label") or result.get("error") or "")[:600]}
        if result.get("background") and result.get("child_id"):
            presentation["references"] = [{"kind": "task", "target": result["child_id"], "label": result.get("label") or result["child_id"]}]
        return presentation

    async def invoke(self, args, ctx=None):
        metadata = (ctx.metadata or {}) if ctx else {}
        parent = metadata.get("run_context")
        conversation = getattr(self.gateway, "conversation_service", None)
        if parent is None or conversation is None:
            raise RuntimeError("Delegation requires an active Conversation Runtime context")
        request = DelegationRequest.model_validate(args)
        if request.run_in_background:
            background = getattr(conversation, "background_agents", None)
            if background is None:
                raise RuntimeError("Persistent child execution is not initialized")
            return await background.start(request, parent=parent, user_config=metadata.get("user_config"))
        return await conversation.delegation.delegate(
            conversation, request, parent=parent, user_config=metadata.get("user_config"),
        )


class AgentControlTool:
    tool_id = name = "subagent.control"
    description = "List or inspect durable child agents, enqueue a follow-up as the child's next FIFO turn, interrupt (pause) a child, or permanently cancel it. The current child turn is not rewritten by send. Only its owning parent can control it."
    input_schema = AgentControlRequest.model_json_schema()
    side_effect_level = "workspace_write"
    side_effect_selector = {"parameter": "action", "default": "workspace_write", "groups": {"read_only": ["list", "get"]}}
    presentation = {"title_i18n": {"zh": "管理子任务", "en": "Manage child agent"}, "subject_arg": "action"}

    def __init__(self, gateway):
        self.gateway = gateway

    async def invoke(self, args, ctx=None):
        metadata = (ctx.metadata or {}) if ctx else {}
        service = getattr(getattr(self.gateway, "conversation_service", None), "background_agents", None)
        if service is None or metadata.get("run_context") is None:
            raise RuntimeError("Persistent child execution requires an active parent context")
        return await service.control(AgentControlRequest.model_validate(args), parent=metadata["run_context"], user_config=metadata.get("user_config"))


class AgentReportTool:
    tool_id = name = "subagent.report"
    description = "Report findings to your direct parent agent. quiet adds context without starting a turn; wakeup asks the Runtime to continue an idle parent. The Runtime supplies sender identity and recipient. Only an actively executing persistent child can report. Completion is reported automatically, even if this tool is not called."
    input_schema = AgentReportRequest.model_json_schema()
    side_effect_level = "workspace_write"
    presentation = {"title_i18n": {"zh": "向父任务汇报", "en": "Report to parent"}, "subject_arg": "content"}

    def __init__(self, gateway):
        self.gateway = gateway

    async def invoke(self, args, ctx=None):
        metadata = (ctx.metadata or {}) if ctx else {}
        service = getattr(getattr(self.gateway, "conversation_service", None), "background_agents", None)
        if service is None or metadata.get("run_context") is None:
            raise RuntimeError("Reporting requires an active child context")
        return service.messages.report(AgentReportRequest.model_validate(args), sender=metadata["run_context"])


def create_tools(runtime: dict[str, Any]) -> list[Any]:
    gateway = runtime.get("gateway_server")
    return [DelegateTool(gateway), AgentControlTool(gateway), AgentReportTool(gateway)] if gateway is not None else []
