"""Gateway package exports.

Keep protocol symbols eager and lazily import heavy services to avoid
import cycles during test collection and runtime bootstrap.
"""

from typing import TYPE_CHECKING

from .protocol import EventType, GatewayProtocol, MessageType, RequestType

if TYPE_CHECKING:
    from .config_service import ConfigService
    from .connection import ConnectionManager
    from .conversation_service import ConversationService
    from .events import EventEmitter
    from .memory_service import MemoryService
    from .reasoning_service import ReasoningService
    from .server import GatewayServer
    from .tool_service import Tool, ToolInvocationContext, ToolService
    from .workflow_engine import WorkflowEngine, WorkflowError
    from .workflow_models import Checkpoint, WorkflowDefinition, WorkflowRun, WorkflowStep

__all__ = [
    "GatewayProtocol",
    "GatewayServer",
    "ConnectionManager",
    "EventEmitter",
    "ToolService",
    "ToolInvocationContext",
    "Tool",
    "MemoryService",
    "ReasoningService",
    "ConversationService",
    "ConfigService",
    "WorkspaceService",
    "WorkspaceHandle",
    "WorkflowEngine",
    "WorkflowError",
    "WorkflowDefinition",
    "WorkflowRun",
    "WorkflowStep",
    "Checkpoint",
    "MessageType",
    "RequestType",
    "EventType",
]


def __getattr__(name: str):
    if name == "GatewayServer":
        from .server import GatewayServer

        return GatewayServer
    if name == "ConnectionManager":
        from .connection import ConnectionManager

        return ConnectionManager
    if name == "EventEmitter":
        from .events import EventEmitter

        return EventEmitter
    if name == "ToolService":
        from .tool_service import ToolService

        return ToolService
    if name == "ToolInvocationContext":
        from .tool_service import ToolInvocationContext

        return ToolInvocationContext
    if name == "Tool":
        from .tool_service import Tool

        return Tool
    if name == "MemoryService":
        from .memory_service import MemoryService

        return MemoryService
    if name == "ReasoningService":
        from .reasoning_service import ReasoningService

        return ReasoningService
    if name == "ConversationService":
        from .conversation_service import ConversationService

        return ConversationService
    if name == "ConfigService":
        from .config_service import ConfigService

        return ConfigService
    if name == "WorkspaceService":
        from .workspace_service import WorkspaceService

        return WorkspaceService
    if name == "WorkspaceHandle":
        from .workspace_service import WorkspaceHandle

        return WorkspaceHandle
    if name == "WorkflowEngine":
        from .workflow_engine import WorkflowEngine

        return WorkflowEngine
    if name == "WorkflowError":
        from .workflow_engine import WorkflowError

        return WorkflowError
    if name == "WorkflowDefinition":
        from .workflow_models import WorkflowDefinition

        return WorkflowDefinition
    if name == "WorkflowRun":
        from .workflow_models import WorkflowRun

        return WorkflowRun
    if name == "WorkflowStep":
        from .workflow_models import WorkflowStep

        return WorkflowStep
    if name == "Checkpoint":
        from .workflow_models import Checkpoint

        return Checkpoint
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
