"""
网关协议定义 - WebSocket通信协议
参考 Clawdbot 的 Gateway Protocol 设计
"""
from enum import Enum
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class MessageType(str, Enum):
    """消息类型"""
    REQUEST = "req"          # 客户端请求
    RESPONSE = "res"         # 服务端响应
    EVENT = "event"          # 服务端事件推送
    

class RequestType(str, Enum):
    """请求类型"""
    CONNECT = "connect"              # 连接握手
    HEALTH = "health"                # 健康检查
    STATUS = "status"                # 状态查询
    SEND = "send"                    # 发送消息
    AGENT = "agent"                  # Agent调用
    CHANNELS_STATUS = "channels.status"  # 通道状态
    SYSTEM_INFO = "system.info"      # 系统信息
    
    # 记忆系统
    MEMORY_QUERY = "memory.query"    # 记忆查询
    MEMORY_CLUSTER = "memory.cluster"  # 记忆聚类
    MEMORY_SUMMARIZE = "memory.summarize"  # 生成摘要
    MEMORY_GRAPH = "memory.graph"    # 获取记忆图
    MEMORY_DECAY = "memory.decay"    # 应用遗忘
    MEMORY_CLEANUP = "memory.cleanup"  # 清理遗忘节点
    
    # 会话管理
    SESSIONS_LIST = "sessions.list"  # 会话列表
    SESSION_DETAIL = "session.detail"  # 会话详情
    SESSION_DELETE = "session.delete"  # 删除会话
    
    # 追问系统
    FOLLOWUP = "followup"            # 气泡追问
    
    # 工具系统
    TOOLS_LIST = "tools.list"        # 工具列表
    TOOL_CALL = "tool.call"          # 工具调用
    
    # 配置管理
    CONFIG_GET = "config.get"              # 获取配置
    CONFIG_RELOAD = "config.reload"        # 重载配置
    CONFIG_UPDATE = "config.update"        # 更新用户配置
    CONFIG_RESET = "config.reset"          # 重置用户配置
    CONFIG_SWITCH_MODEL = "config.switch_model"  # 切换模型
    CONFIG_DIAGNOSE = "config.diagnose"    # 诊断配置
    
    # 电脑控制
    COMPUTER_BROWSER = "computer.browser"      # 浏览器控制
    COMPUTER_SCREEN = "computer.screen"        # 屏幕控制
    COMPUTER_FILESYSTEM = "computer.filesystem"  # 文件系统
    COMPUTER_PROCESS = "computer.process"      # 进程管理
    COMPUTER_STATUS = "computer.status"        # 控制器状态
    

class EventType(str, Enum):
    """事件类型"""
    CONNECTED = "connected"          # 连接成功
    DISCONNECTED = "disconnected"    # 连接断开
    AGENT_START = "agent.start"      # Agent开始
    AGENT_STREAM = "agent.stream"    # Agent流式输出
    AGENT_COMPLETE = "agent.complete"  # Agent完成
    AGENT_ERROR = "agent.error"      # Agent错误
    CHANNEL_MESSAGE = "channel.message"  # 通道消息
    HEALTH_UPDATE = "health.update"  # 健康状态更新
    HEARTBEAT = "heartbeat"          # 心跳
    MEMORY_UPDATE = "memory.update"  # 记忆更新
    # 记忆系统生命周期事件
    MEMORY_SAVED = "memory.saved"              # 记忆已保存
    MEMORY_RECALLED = "memory.recalled"        # 记忆已召回
    MEMORY_CLUSTERED = "memory.clustered"      # 记忆已聚类
    MEMORY_SUMMARIZED = "memory.summarized"    # 记忆已摘要
    # 工具调用生命周期（供 ToolService / 多 Agent 调度 使用）
    TOOL_CALL_START = "tool.call.start"
    TOOL_CALL_RESULT = "tool.call.result"
    TOOL_CALL_ERROR = "tool.call.error"
    # 对话系统生命周期事件
    CONVERSATION_START = "conversation.start"      # 对话开始
    CONVERSATION_COMPLETE = "conversation.complete"  # 对话完成
    CONVERSATION_ERROR = "conversation.error"      # 对话错误
    # 配置系统生命周期事件
    CONFIG_CHANGED = "config.changed"              # 配置已变更（用户级）
    CONFIG_RELOADED = "config.reloaded"            # 配置已重载（系统级）
    

class DeviceRole(str, Enum):
    """设备角色"""
    CLIENT = "client"        # 普通客户端
    NODE = "node"           # 节点（提供能力）
    ADMIN = "admin"         # 管理员


class NodeCapability(str, Enum):
    """节点能力"""
    COMPUTE = "compute"      # 计算能力
    STORAGE = "storage"      # 存储能力
    CAMERA = "camera"        # 摄像头
    LOCATION = "location"    # 位置服务
    BROWSER = "browser"      # 浏览器自动化


# ============ 基础协议模型 ============

class DeviceIdentity(BaseModel):
    """设备身份"""
    device_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_name: str
    device_type: str = "unknown"  # desktop, mobile, server, etc.
    role: DeviceRole = DeviceRole.CLIENT
    capabilities: List[NodeCapability] = Field(default_factory=list)
    

class ConnectParams(BaseModel):
    """连接参数"""
    identity: DeviceIdentity
    token: Optional[str] = None  # 认证令牌
    protocol_version: str = "1.0"
    client_version: Optional[str] = None
    

class RequestMessage(BaseModel):
    """请求消息"""
    type: MessageType = MessageType.REQUEST
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: RequestType
    params: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None  # 幂等性键
    timestamp: datetime = Field(default_factory=datetime.now)
    

class ResponseMessage(BaseModel):
    """响应消息"""
    type: MessageType = MessageType.RESPONSE
    id: str  # 对应请求的ID
    ok: bool
    payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    

class EventMessage(BaseModel):
    """事件消息"""
    type: MessageType = MessageType.EVENT
    event: EventType
    payload: Dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None  # 事件序列号
    timestamp: datetime = Field(default_factory=datetime.now)
    

# ============ 特定请求参数 ============

class SendMessageParams(BaseModel):
    """发送消息参数"""
    channel: str  # 通道名称 (dingtalk, feishu, wecom, web)
    target: str   # 目标 (group_id, user_id, etc.)
    content: str
    message_type: str = "text"  # text, markdown, card, etc.
    metadata: Dict[str, Any] = Field(default_factory=dict)
    

class AgentCallParams(BaseModel):
    """Agent调用参数"""
    agent_name: str
    prompt: str
    session_id: Optional[str] = None
    stream: bool = True
    context: Dict[str, Any] = Field(default_factory=dict)
    tools_enabled: bool = True
    

class MemoryQueryParams(BaseModel):
    """记忆查询参数"""
    query: str
    session_id: Optional[str] = None
    search_type: str = "hybrid"  # semantic, graph, temporal, hybrid
    top_k: int = 5
    filters: Dict[str, Any] = Field(default_factory=dict)


class FollowupParams(BaseModel):
    """追问参数"""
    selected_text: str
    query_type: str = "why"  # why, risk, alternative, custom
    custom_query: Optional[str] = None
    session_id: str = "default"


class SessionParams(BaseModel):
    """会话参数"""
    session_id: str


class MemoryClusterParams(BaseModel):
    """记忆聚类参数"""
    session_id: str


class MemorySummarizeParams(BaseModel):
    """记忆摘要参数"""
    session_id: str
    incremental: bool = False


class ConfigReloadParams(BaseModel):
    """配置重载参数"""
    config_path: Optional[str] = None


class ComputerControlParams(BaseModel):
    """电脑控制参数"""
    capability: str  # browser, screen, filesystem, process
    action: str      # 具体操作
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = 30
    

# ============ 响应载荷 ============

class HealthPayload(BaseModel):
    """健康状态载荷"""
    status: str  # healthy, degraded, unhealthy
    uptime: float
    active_connections: int
    channels: Dict[str, Dict[str, Any]]
    memory_usage: Optional[Dict[str, Any]] = None
    

class StatusPayload(BaseModel):
    """状态载荷"""
    gateway_status: str
    channels_status: Dict[str, Dict[str, Any]]
    agents_status: Dict[str, Dict[str, Any]]
    nodes_status: Dict[str, Dict[str, Any]]
    

class AgentResponsePayload(BaseModel):
    """Agent响应载荷"""
    run_id: str
    status: str  # accepted, running, completed, error
    result: Optional[str] = None
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    

# ============ 事件载荷 ============

class AgentStreamPayload(BaseModel):
    """Agent流式输出载荷"""
    run_id: str
    chunk: str
    finished: bool = False
    

class ChannelMessagePayload(BaseModel):
    """通道消息载荷"""
    channel: str
    sender: str
    content: str
    message_type: str
    timestamp: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GatewayProtocol:
    """网关协议工具类"""
    
    @staticmethod
    def create_request(
        method: RequestType,
        params: Dict[str, Any],
        idempotency_key: Optional[str] = None
    ) -> RequestMessage:
        """创建请求消息"""
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
        """创建响应消息"""
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
        """创建事件消息"""
        return EventMessage(
            event=event,
            payload=payload,
            seq=seq
        )
    
    @staticmethod
    def parse_message(data: str) -> Union[RequestMessage, ResponseMessage, EventMessage]:
        """解析消息"""
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
