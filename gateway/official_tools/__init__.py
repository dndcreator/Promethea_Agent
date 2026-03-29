from __future__ import annotations

from typing import Any

from .command_tools import RuntimeExecCommandTool, RuntimeReadEnvTool
from .data_tools import DataCsvToJsonTool, DataJsonToCsvTool
from .math_tools import MathCalculateTool
from .memory_tools import (
    MemoryCreateEntryTool,
    MemoryGetContextTool,
    MemoryListEntriesTool,
    MemoryRecallRunsTool,
    MemorySummarizeSessionTool,
)
from .runtime_tools import RuntimeListToolsTool, RuntimeProcessingStatsTool, RuntimeServicesTool
from .session_tools import SessionInfoTool, SessionListTool, SessionRecentMessagesTool
from .text_tools import TextFindMatchesTool, TextNormalizeJsonTool, TextWordStatsTool
from .utility_tools import UtilsHashTextTool, UtilsNowTool, UtilsUuidTool
from .web_tools import (
    WebDownloadToWorkspaceTool,
    WebExtractLinksTool,
    WebFetchJsonTool,
    WebFetchTextTool,
    WebSearchTool,
)
from .workflow_tools import (
    WorkflowApproveStepTool,
    WorkflowCheckpointsTool,
    WorkflowDefineTool,
    WorkflowListRunsTool,
    WorkflowListTool,
    WorkflowPauseTool,
    WorkflowResumeTool,
    WorkflowRetryStepTool,
    WorkflowStartTool,
    WorkflowStatusTool,
)
from .workspace_tools import (
    WorkspaceCopyFileTool,
    WorkspaceDeleteFileTool,
    WorkspaceEnsureDirTool,
    WorkspaceFileInfoTool,
    WorkspaceGlobFilesTool,
    WorkspaceListFilesTool,
    WorkspaceMoveFileTool,
    WorkspaceReadFilesTool,
    WorkspaceReadFileTool,
    WorkspaceReplaceTextTool,
    WorkspaceSearchTextTool,
    WorkspaceTailFileTool,
    WorkspaceWriteFileTool,
)


def register_official_tools(
    *,
    tool_service: Any,
    workspace_service: Any = None,
    memory_service: Any = None,
    message_manager: Any = None,
    gateway_server: Any = None,
) -> None:
    """Register built-in local tools with the runtime ToolService."""
    if tool_service is None:
        return
    existing = getattr(tool_service, "_registered_tools", {}) or {}
    tools = [
        DataCsvToJsonTool(),
        DataJsonToCsvTool(),
        MathCalculateTool(),
        TextWordStatsTool(),
        TextFindMatchesTool(),
        TextNormalizeJsonTool(),
        UtilsNowTool(),
        UtilsUuidTool(),
        UtilsHashTextTool(),
        WebFetchTextTool(),
        WebFetchJsonTool(),
        WebSearchTool(),
        WebExtractLinksTool(),
        RuntimeExecCommandTool(),
        RuntimeReadEnvTool(),
    ]
    if memory_service is not None:
        tools.extend(
            [
                MemoryGetContextTool(memory_service=memory_service),
                MemoryListEntriesTool(memory_service=memory_service),
                MemoryCreateEntryTool(memory_service=memory_service),
                MemorySummarizeSessionTool(memory_service=memory_service),
                MemoryRecallRunsTool(memory_service=memory_service),
            ]
        )
    if message_manager is not None:
        tools.extend(
            [
                SessionRecentMessagesTool(message_manager=message_manager),
                SessionInfoTool(message_manager=message_manager),
                SessionListTool(message_manager=message_manager),
            ]
        )
    if gateway_server is not None:
        tools.extend(
            [
                RuntimeServicesTool(gateway_server=gateway_server),
                RuntimeProcessingStatsTool(gateway_server=gateway_server),
                RuntimeListToolsTool(gateway_server=gateway_server),
            ]
        )
        if getattr(gateway_server, "workflow_engine", None) is not None:
            tools.extend(
                [
                    WorkflowDefineTool(gateway_server=gateway_server),
                    WorkflowListTool(gateway_server=gateway_server),
                    WorkflowStartTool(gateway_server=gateway_server),
                    WorkflowStatusTool(gateway_server=gateway_server),
                    WorkflowListRunsTool(gateway_server=gateway_server),
                    WorkflowPauseTool(gateway_server=gateway_server),
                    WorkflowResumeTool(gateway_server=gateway_server),
                    WorkflowRetryStepTool(gateway_server=gateway_server),
                    WorkflowApproveStepTool(gateway_server=gateway_server),
                    WorkflowCheckpointsTool(gateway_server=gateway_server),
                ]
            )
    if workspace_service is not None:
        tools.extend(
            [
                WebDownloadToWorkspaceTool(workspace_service=workspace_service),
                WorkspaceCopyFileTool(workspace_service=workspace_service),
                WorkspaceDeleteFileTool(workspace_service=workspace_service),
                WorkspaceEnsureDirTool(workspace_service=workspace_service),
                WorkspaceFileInfoTool(workspace_service=workspace_service),
                WorkspaceGlobFilesTool(workspace_service=workspace_service),
                WorkspaceListFilesTool(workspace_service=workspace_service),
                WorkspaceMoveFileTool(workspace_service=workspace_service),
                WorkspaceReadFilesTool(workspace_service=workspace_service),
                WorkspaceReadFileTool(workspace_service=workspace_service),
                WorkspaceReplaceTextTool(workspace_service=workspace_service),
                WorkspaceWriteFileTool(workspace_service=workspace_service),
                WorkspaceSearchTextTool(workspace_service=workspace_service),
                WorkspaceTailFileTool(workspace_service=workspace_service),
            ]
        )
    for tool in tools:
        if getattr(tool, "tool_id", None) in existing:
            continue
        tool_service.register_tool(tool)
