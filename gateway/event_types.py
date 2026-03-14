"""Centralized canonical gateway lifecycle event names."""

GATEWAY_REQUEST_RECEIVED = "gateway.request.received"
GATEWAY_RUN_STARTED = "gateway.run.started"
CONVERSATION_RUN_STARTED = "conversation.run.started"
MEMORY_RECALL_STARTED = "memory.recall.started"
MEMORY_RECALL_FINISHED = "memory.recall.finished"
REASONING_STARTED = "reasoning.started"
REASONING_FINISHED = "reasoning.finished"
TOOL_EXECUTION_STARTED = "tool.execution.started"
TOOL_EXECUTION_FINISHED = "tool.execution.finished"
TOOL_EXECUTION_FAILED = "tool.execution.failed"
RESPONSE_SYNTHESIZED = "response.synthesized"
MEMORY_WRITE_DECIDED = "memory.write.decided"
GATEWAY_RUN_FINISHED = "gateway.run.finished"
WORKSPACE_ARTIFACT_WRITTEN = "workspace.artifact.written"
WORKSPACE_WRITE_BLOCKED = "workspace.write.blocked"
WORKFLOW_RUN_STARTED = "workflow.run.started"
WORKFLOW_RUN_PAUSED = "workflow.run.paused"
WORKFLOW_RUN_RESUMED = "workflow.run.resumed"
WORKFLOW_RUN_COMPLETED = "workflow.run.completed"
WORKFLOW_STEP_WAITING_HUMAN = "workflow.step.waiting_human"

ALL_EVENT_TYPES = [
    GATEWAY_REQUEST_RECEIVED,
    GATEWAY_RUN_STARTED,
    CONVERSATION_RUN_STARTED,
    MEMORY_RECALL_STARTED,
    MEMORY_RECALL_FINISHED,
    REASONING_STARTED,
    REASONING_FINISHED,
    TOOL_EXECUTION_STARTED,
    TOOL_EXECUTION_FINISHED,
    TOOL_EXECUTION_FAILED,
    RESPONSE_SYNTHESIZED,
    MEMORY_WRITE_DECIDED,
    GATEWAY_RUN_FINISHED,
    WORKSPACE_ARTIFACT_WRITTEN,
    WORKSPACE_WRITE_BLOCKED,
    WORKFLOW_RUN_STARTED,
    WORKFLOW_RUN_PAUSED,
    WORKFLOW_RUN_RESUMED,
    WORKFLOW_RUN_COMPLETED,
    WORKFLOW_STEP_WAITING_HUMAN,
]




