# Gateway 模块

Gateway 是 Promethea Agent 的核心运行平台，采用**微内核 + 事件总线**架构，参考 Moltbot 设计。

## 架构设计

Gateway 本身只是一个**协议层 + 事件总线**，具体能力通过依赖注入提供：

```
┌─────────────────────────────────────┐
│      GatewayServer (运行平台)        │
│  - WebSocket/HTTP 协议处理           │
│  - EventEmitter (事件总线)           │
│  - ConnectionManager (连接管理)      │
└─────────────────────────────────────┘
              │
    ┌─────────┼─────────┬─────────┐
    ▼         ▼         ▼         ▼
ToolService MemoryService ConversationService ConfigService
```

## 核心组件

### 1. GatewayServer (`server.py`)

- **职责**: WebSocket 服务器核心，处理客户端连接和消息路由
- **特点**: 
  - 依赖注入设计，不直接 import 其他子系统
  - 通过事件总线与其他服务通信
  - 支持幂等性缓存、请求去重

### 2. EventEmitter (`events.py`)

- **职责**: 事件总线，实现发布-订阅模式
- **事件类型**: 定义在 `protocol.py` 的 `EventType` 枚举中
- **用途**: 服务间解耦通信

### 3. ConnectionManager (`connection.py`)

- **职责**: 管理 WebSocket 连接
- **功能**: 连接注册、心跳检测、自动重连

### 4. 一级服务

#### ToolService (`tool_service.py`)
- 工具注册、查询、调用
- 支持 MCP 工具和本地工具
- 发出 `TOOL_CALL_*` 事件

#### MemoryService (`memory_service.py`)
- 记忆查询、聚类、摘要
- 订阅 `CHANNEL_MESSAGE` 自动保存记忆
- 发出 `MEMORY_*` 事件

#### ConversationService (`conversation_service.py`)
- 核心对话流程处理
- LLM 调用、工具调用循环
- 订阅 `CHANNEL_MESSAGE` 自动处理对话
- 发出 `CONVERSATION_*` 事件

#### ConfigService (`config_service.py`)
- 配置管理（默认、用户、环境变量）
- 配置热重载
- 模型切换等功能的总集成
- 发出 `CONFIG_CHANGED` 事件

## 协议定义

### RequestType (请求类型)

客户端可以发送的请求类型，定义在 `protocol.py` 中：
- `TOOLS_LIST` - 列出可用工具
- `TOOL_CALL` - 调用工具
- `MEMORY_QUERY` - 查询记忆
- `CONVERSATION_FOLLOWUP` - 对话跟进
- `CONFIG_GET` - 获取配置
- 等等...

### EventType (事件类型)

服务间通信的事件类型：
- `CHANNEL_MESSAGE` - 通道消息
- `TOOL_CALL_START/RESULT/ERROR` - 工具调用事件
- `MEMORY_SAVED/RECALLED/CLUSTERED` - 记忆事件
- `CONVERSATION_START/COMPLETE/ERROR` - 对话事件
- `CONFIG_CHANGED` - 配置变更事件

## 使用示例

### 初始化 Gateway

```python
from gateway import GatewayServer, EventEmitter, ConnectionManager
from gateway_integration import GatewayIntegration

# GatewayIntegration 负责组装所有依赖
gateway_integration = GatewayIntegration()
gateway_integration.initialize()
```

### 订阅事件

```python
event_emitter = gateway_integration.get_event_emitter()

async def on_message(event_msg):
    print(f"收到消息: {event_msg.payload}")

event_emitter.on(EventType.CHANNEL_MESSAGE, on_message)
```

### 发送事件

```python
await event_emitter.emit(EventType.CONFIG_CHANGED, {
    "user_id": "user_123",
    "changes": {"api": {"model": "gpt-4"}}
})
```

## 设计原则

1. **依赖注入**: Gateway 不直接 import 其他模块，通过构造函数注入
2. **事件驱动**: 服务间通过事件总线通信，实现解耦
3. **可扩展性**: 新服务只需实现接口并注册到 Gateway
4. **向后兼容**: 支持降级处理，即使某些服务不可用也能运行

## 相关文档

- [主 README](../README.md)
- [架构文档](../docs/ARCHITECTURE.md)
- [配置管理](../config/README.md)
