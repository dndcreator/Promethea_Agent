"""
Gateway protocol definition - WebSocket communication protocol.

Loosely inspired by the Clawdbot Gateway Protocol design.
"""
from enum import Enum
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class MessageType(str, Enum):
    """High-level message type."""
    REQUEST = "req"          # Client request
    RESPONSE = "res"         # Server response
    EVENT = "event"          # Server-side event push
    

class RequestType(str, Enum):
    """Request method type."""
    CONNECT = "connect"              # Connection handshake
    HEALTH = "health"                # Health check
    STATUS = "status"                # Status query
    SEND = "send"                    # Send a message
    AGENT = "agent"                  # Agent invocation
    CHANNELS_STATUS = "channels.status"  # Channel status
    SYSTEM_INFO = "system.info"      # System information
    
    # Memory system
    MEMORY_QUERY = "memory.query"    # Memory query
    MEMORY_CLUSTER = "memory.cluster"  # Memory clustering
    MEMORY_SUMMARIZE = "memory.summarize"  # Summary generation
    MEMORY_GRAPH = "memory.graph"    # Retrieve memory graph
    MEMORY_DECAY = "memory.decay"    # Apply forgetting
    MEMORY_CLEANUP = "memory.cleanup"  # Cleanup forgotten nodes
    MEMORY_RECALL_RUNS = "memory.recall.runs"  # Recall inspector run list
    MEMORY_RECALL_INSPECT = "memory.recall.inspect"  # Recall inspector detail
    
    # Session management
    SESSIONS_LIST = "sessions.list"  # List sessions
    SESSION_DETAIL = "session.detail"  # Session detail
    SESSION_DELETE = "session.delete"  # Delete session
    
    # Follow-up system
    FOLLOWUP = "followup"            # Bubble follow-up query
    CHAT = "chat"                    # Chat turn
    CHAT_CONFIRM = "chat.confirm"    # Confirm sensitive tool execution
    BATCH = "batch"                  # Batch gateway request
    
    # Tool system
    TOOLS_LIST = "tools.list"        # Tool list
    TOOL_CALL = "tool.call"          # Tool invocation
    MCP_SERVICES_LIST = "mcp.services.list"     # MCP services
    MCP_SERVICE_HEALTH = "mcp.service.health"   # MCP service health
    MCP_SERVICE_TOOLS = "mcp.service.tools"     # MCP tools by service
    MCP_VISIBLE_TOOLS = "mcp.tools.visible"     # MCP visible tools for user
    # Configuration management
    CONFIG_GET = "config.get"              # Get configuration
    CONFIG_RELOAD = "config.reload"        # Reload configuration
    CONFIG_UPDATE = "config.update"        # Update user configuration
    CONFIG_RESET = "config.reset"          # Reset user configuration
    CONFIG_SWITCH_MODEL = "config.switch_model"  # Switch model
    CONFIG_DIAGNOSE = "config.diagnose"    # Diagnose configuration

    # Workspace sandbox
    WORKSPACE_CREATE_DOCUMENT = "workspace.create_document"
    WORKSPACE_UPDATE_DOCUMENT = "workspace.update_document"
    WORKSPACE_LIST_ARTIFACTS = "workspace.list_artifacts"
    WORKSPACE_SNAPSHOT_ARTIFACT = "workspace.snapshot_artifact"
    
    # Workflow engine
    WORKFLOW_DEFINE = "workflow.define"
    WORKFLOW_LIST = "workflow.list"
    WORKFLOW_START = "workflow.start"
    WORKFLOW_STATUS = "workflow.status"
    WORKFLOW_PAUSE = "workflow.pause"
    WORKFLOW_RESUME = "workflow.resume"
    WORKFLOW_RETRY_STEP = "workflow.retry_step"
    WORKFLOW_APPROVE_STEP = "workflow.approve_step"
    WORKFLOW_CHECKPOINTS = "workflow.checkpoints"

    # Computer control
    COMPUTER_BROWSER = "computer.browser"      # Browser control
    COMPUTER_SCREEN = "computer.screen"        # Screen capture/control
    COMPUTER_FILESYSTEM = "computer.filesystem"  # File system
    COMPUTER_PROCESS = "computer.process"      # Process management
    COMPUTER_STATUS = "computer.status"        # Controller status
    

class EventType(str, Enum):
    """Event type."""
    CONNECTED = "connected"          # Connection established
    DISCONNECTED = "disconnected"    # Connection closed
    AGENT_START = "agent.start"      # Agent run started
    AGENT_STREAM = "agent.stream"    # Agent streaming output
    AGENT_COMPLETE = "agent.complete"  # Agent run completed
    AGENT_ERROR = "agent.error"      # Agent error
    CHANNEL_MESSAGE = "channel.message"  # Channel message
    HEALTH_UPDATE = "health.update"  # Health status update
    HEARTBEAT = "heartbeat"          # Heartbeat ping
    MEMORY_UPDATE = "memory.update"  # Memory updated
    # Memory system lifecycle events
    MEMORY_SAVED = "memory.saved"              # Memory saved
    MEMORY_RECALLED = "memory.recalled"        # Memory recalled
    MEMORY_CLUSTERED = "memory.clustered"      # Memory clustered
    MEMORY_SUMMARIZED = "memory.summarized"    # Memory summarized
    # Tool invocation lifecycle (for ToolService / multi-agent scheduling)
    TOOL_CALL_START = "tool.call.start"
    TOOL_CALL_RESULT = "tool.call.result"
    TOOL_CALL_ERROR = "tool.call.error"
    # Conversation lifecycle events
    CONVERSATION_START = "conversation.start"      # Conversation started
    CONVERSATION_COMPLETE = "conversation.complete"  # Conversation completed
    CONVERSATION_ERROR = "conversation.error"      # Conversation error
    # Full interaction event (user input + assistant output)
    INTERACTION_COMPLETED = "interaction.completed"
    # Reasoning lifecycle events
    REASONING_START = "reasoning.start"
    REASONING_NODE_CREATED = "reasoning.node.created"
    REASONING_NODE_COMPLETED = "reasoning.node.completed"
    REASONING_MEMORY_REQUESTED = "reasoning.memory.requested"
    REASONING_TOOL_REQUESTED = "reasoning.tool.requested"
    REASONING_OBSERVATION_RECEIVED = "reasoning.observation.received"
    REASONING_REPLAN = "reasoning.replan"
    REASONING_COMPLETE = "reasoning.complete"
    REASONING_ERROR = "reasoning.error"
    # Configuration lifecycle events
    CONFIG_CHANGED = "config.changed"              # Configuration changed (per-user)
    CONFIG_RELOADED = "config.reloaded"            # Configuration reloaded (system-wide)
    REQUEST_RECEIVED = "request.received"
    REQUEST_COMPLETED = "request.completed"
    REQUEST_FAILED = "request.failed"
    # Canonical gateway protocol lifecycle events (Backlog 002)
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
    SECURITY_BOUNDARY_VIOLATION = "security.boundary.violation"
    SECURITY_SECRET_ACCESS = "security.secret.access"
    CONVERSATION_STAGE_STARTED = "conversation.stage.started"
    CONVERSATION_STAGE_FINISHED = "conversation.stage.finished"
    CONVERSATION_STAGE_FAILED = "conversation.stage.failed"
    WORKFLOW_RUN_STARTED = "workflow.run.started"
    WORKFLOW_RUN_PAUSED = "workflow.run.paused"
    WORKFLOW_RUN_RESUMED = "workflow.run.resumed"
    WORKFLOW_RUN_COMPLETED = "workflow.run.completed"
    WORKFLOW_STEP_WAITING_HUMAN = "workflow.step.waiting_human"
    

class DeviceRole(str, Enum):
    """Logical device role in the gateway ecosystem."""
    CLIENT = "client"        # Regular client
    NODE = "node"           # Node that exposes capabilities
    ADMIN = "admin"         # Administrator


class NodeCapability(str, Enum):
    """Capabilities that a node can provide."""
    COMPUTE = "compute"      # Compute capability
    STORAGE = "storage"      # Storage capability
    CAMERA = "camera"        # Camera
    LOCATION = "location"    # Location service
    BROWSER = "browser"      # Browser automation


# ============ Base protocol models ============

class DeviceIdentity(BaseModel):
    """Device identity information."""
    device_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_name: str
    device_type: str = "unknown"  # desktop, mobile, server, etc.
    role: DeviceRole = DeviceRole.CLIENT
    capabilities: List[NodeCapability] = Field(default_factory=list)
    

class ConnectParams(BaseModel):
    """Connection parameters for the initial handshake."""
    identity: DeviceIdentity
    token: Optional[str] = None  # Optional authentication token
    protocol_version: str = "1.0"
    client_version: Optional[str] = None
    

class RequestMessage(BaseModel):
    """Generic request message envelope."""
    type: MessageType = MessageType.REQUEST
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: RequestType
    params: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None  # Idempotency key
    timestamp: datetime = Field(default_factory=datetime.now)
    

class ResponseMessage(BaseModel):
    """Generic response message envelope."""
    type: MessageType = MessageType.RESPONSE
    id: str  # Corresponding request ID
    ok: bool
    payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    

class EventMessage(BaseModel):
    """Generic event message envelope."""
    type: MessageType = MessageType.EVENT
    event: EventType
    payload: Dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None  # Event sequence number
    timestamp: datetime = Field(default_factory=datetime.now)
    

# ============ Specific request payloads ============

class SendMessageParams(BaseModel):
    """Payload for sending a channel message."""
    channel: str  # Channel name (dingtalk, feishu, wecom, web)
    target: str   # Target (group_id, user_id, etc.)
    content: str
    message_type: str = "text"  # text, markdown, card, etc.
    metadata: Dict[str, Any] = Field(default_factory=dict)
    

class AgentCallParams(BaseModel):
    """Payload for an Agent invocation."""
    agent_name: str
    prompt: str
    session_id: Optional[str] = None
    stream: bool = True
    context: Dict[str, Any] = Field(default_factory=dict)
    tools_enabled: bool = True
    

class MemoryQueryParams(BaseModel):
    """Payload for querying the memory system."""
    query: str
    session_id: Optional[str] = None
    search_type: str = "hybrid"  # semantic, graph, temporal, hybrid
    top_k: int = 5
    filters: Dict[str, Any] = Field(default_factory=dict)


class FollowupParams(BaseModel):
    """Payload for a follow-up (bubble) question."""
    selected_text: str
    query_type: str = "why"  # why, risk, alternative, custom
    custom_query: Optional[str] = None
    session_id: str = "default"


class ChatParams(BaseModel):
    message: str
    session_id: Optional[str] = None
    stream: bool = False


class ChatConfirmParams(BaseModel):
    session_id: str
    tool_call_id: str
    action: str


class SessionParams(BaseModel):
    """Payload that only contains a session id."""
    session_id: str


class MemoryClusterParams(BaseModel):
    """Payload for memory clustering."""
    session_id: str


class MemorySummarizeParams(BaseModel):
    """Payload for memory summarisation."""
    session_id: str
    incremental: bool = False


class ConfigReloadParams(BaseModel):
    """Payload for configuration reload requests."""
    config_path: Optional[str] = None


class ConfigUpdateParams(BaseModel):
    """User config update params"""
    config_data: Dict[str, Any] = Field(default_factory=dict)
    validate_config: bool = Field(default=True, alias="validate")


class ConfigSwitchModelParams(BaseModel):
    """Payload to switch a user's model/API configuration."""
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class ComputerControlParams(BaseModel):
    """Payload for computer-control actions."""
    capability: str  # browser, screen, filesystem, process
    action: str      # Specific operation
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = 30
    

# ============ Response payloads ============

class HealthPayload(BaseModel):
    """Health status payload."""
    status: str  # healthy, degraded, unhealthy
    uptime: float
    active_connections: int
    channels: Dict[str, Dict[str, Any]]
    memory_usage: Optional[Dict[str, Any]] = None
    

class StatusPayload(BaseModel):
    """High-level gateway status payload."""
    gateway_status: str
    channels_status: Dict[str, Dict[str, Any]]
    agents_status: Dict[str, Dict[str, Any]]
    nodes_status: Dict[str, Dict[str, Any]]
    

class AgentResponsePayload(BaseModel):
    """Agent response payload."""
    run_id: str
    status: str  # accepted, running, completed, error
    result: Optional[str] = None
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    

# ============ Event payloads ============

class AgentStreamPayload(BaseModel):
    """Agent streaming output payload."""
    run_id: str
    chunk: str
    finished: bool = False
    

class ChannelMessagePayload(BaseModel):
    """Channel message payload."""
    channel: str
    sender: str
    content: str
    message_type: str
    timestamp: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)



class GatewayRequest(BaseModel):
    """Unified gateway boundary request object."""

    request_id: str
    trace_id: str
    session_id: Optional[str] = None
    user_id: str
    agent_id: Optional[str] = None
    channel_id: Optional[str] = None
    input_text: str = ""
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    requested_mode: Optional[str] = None
    requested_skill: Optional[str] = None
    requested_workflow: Optional[str] = None
    debug_flags: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)

    @classmethod
    def from_request(
        cls,
        *,
        request: "RequestMessage",
        user_id: str,
        session_id: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> "GatewayRequest":
        params = dict(request.params or {})
        resolved_session = session_id or params.get("session_id")
        trace_id = str(params.get("trace_id") or f"trace_{request.id}")
        input_text = str(
            params.get("message")
            or params.get("query")
            or params.get("text")
            or ""
        )
        return cls(
            request_id=request.id,
            trace_id=trace_id,
            session_id=resolved_session,
            user_id=str(user_id),
            agent_id=params.get("agent_id"),
            channel_id=channel_id,
            input_text=input_text,
            input_payload=params,
            attachments=params.get("attachments") or [],
            metadata=params.get("metadata") or {},
            requested_mode=params.get("requested_mode"),
            requested_skill=params.get("requested_skill"),
            requested_workflow=params.get("requested_workflow"),
            debug_flags=params.get("debug_flags") or {},
        )


class GatewayResponse(BaseModel):
    """Unified gateway boundary response object."""

    request_id: str
    trace_id: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    user_message: Optional[str] = None
    channel: str = "web"
    include_recent: bool = True
    response_text: str = ""
    response_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    tool_summary: Dict[str, Any] = Field(default_factory=dict)
    reasoning_summary: Dict[str, Any] = Field(default_factory=dict)
    memory_write_summary: Dict[str, Any] = Field(default_factory=dict)
    status: str = "success"
    error: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "response_text": self.response_text,
            "response_blocks": self.response_blocks,
            "artifacts": self.artifacts,
            "tool_summary": self.tool_summary,
            "reasoning_summary": self.reasoning_summary,
            "memory_write_summary": self.memory_write_summary,
            "status": self.status,
            "error": self.error,
            "metrics": self.metrics,
            # Backward-compatible fields used by existing callers.
            "response": self.response_text,
        }
        return payload


class GatewayEvent(BaseModel):
    """Unified structured gateway event object."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    user_message: Optional[str] = None
    channel: str = "web"
    include_recent: bool = True
    timestamp: datetime = Field(default_factory=datetime.now)
    source_module: str = "gateway"
    payload: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "info"
    tags: List[str] = Field(default_factory=list)


class ConversationRunInput(BaseModel):
    """Structured conversation-service input contract."""

    model_config = {"arbitrary_types_allowed": True}

    messages: List[Dict[str, Any]] = Field(default_factory=list)
    user_config: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    user_message: Optional[str] = None
    channel: str = "web"
    include_recent: bool = True
    run_context: Optional[Any] = None
    tool_executor: Optional[Any] = None


class ConversationRunOutput(BaseModel):
    """Structured conversation-service output contract."""

    status: str = "success"
    content: str = ""
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = Field(default_factory=dict)

class NormalizedInput(BaseModel):
    user_message: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    channel: str = "web"
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    recent_messages: List[Dict[str, Any]] = Field(default_factory=list)


class ModeDecision(BaseModel):
    mode: str = "fast"
    reason: str = "default"
    confidence: float = 0.5


class MemoryRecallBundle(BaseModel):
    recalled: bool = False
    context: str = ""
    reason: str = "not_needed"
    source: str = "memory_service"
    confidence: float = 0.0


class PlanResult(BaseModel):
    used_reasoning: bool = False
    system_prompt: str = ""
    base_system_prompt: str = ""
    reasoning: Dict[str, Any] = Field(default_factory=dict)


class ToolExecutionBundle(BaseModel):
    enabled: bool = False
    strategy: str = "llm_native"
    tool_executor: Optional[Any] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResponseDraft(BaseModel):
    status: str = "success"
    content: str = ""
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    response_data: Dict[str, Any] = Field(default_factory=dict)

class GatewayProtocol:
    """Helper utilities for building/parsing gateway protocol messages."""
    
    @staticmethod
    def create_request(
        method: RequestType,
        params: Dict[str, Any],
        idempotency_key: Optional[str] = None
    ) -> RequestMessage:
        """Create a request message."""
        return RequestMessage(
            method=method,
            params=params,
            idempotency_key=idempotency_key
        )
    
    @staticmethod
    def create_response(
        request_id: str,
        ok: bool,
        payload: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> ResponseMessage:
        """Create a response message."""
        return ResponseMessage(
            id=request_id,
            ok=ok,
            payload=payload,
            error=error
        )
    
    @staticmethod
    def create_event(
        event: EventType,
        payload: Dict[str, Any],
        seq: Optional[int] = None
    ) -> EventMessage:
        """Create an event message."""
        return EventMessage(
            event=event,
            payload=payload,
            seq=seq
        )
    
    @staticmethod
    def parse_message(data: str) -> Union[RequestMessage, ResponseMessage, EventMessage]:
        """Parse an incoming JSON string into a protocol message."""
        import json
        raw = json.loads(data)
        msg_type = raw.get('type')
        
        if msg_type == MessageType.REQUEST:
            return RequestMessage(**raw)
        elif msg_type == MessageType.RESPONSE:
            return ResponseMessage(**raw)
        elif msg_type == MessageType.EVENT:
            return EventMessage(**raw)
        else:
            raise ValueError(f"Unknown message type: {msg_type}")













