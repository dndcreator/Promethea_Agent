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
    
    # Configuration management
    CONFIG_GET = "config.get"              # Get configuration
    CONFIG_RELOAD = "config.reload"        # Reload configuration
    CONFIG_UPDATE = "config.update"        # Update user configuration
    CONFIG_RESET = "config.reset"          # Reset user configuration
    CONFIG_SWITCH_MODEL = "config.switch_model"  # Switch model
    CONFIG_DIAGNOSE = "config.diagnose"    # Diagnose configuration
    
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
    # Configuration lifecycle events
    CONFIG_CHANGED = "config.changed"              # Configuration changed (per-user)
    CONFIG_RELOADED = "config.reloaded"            # Configuration reloaded (system-wide)
    REQUEST_RECEIVED = "request.received"
    REQUEST_COMPLETED = "request.completed"
    REQUEST_FAILED = "request.failed"
    

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
    validate: bool = True


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
