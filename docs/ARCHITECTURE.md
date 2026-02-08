# 普罗米娅 Agent 核心架构流程

## 架构概览

普罗米娅 Agent 采用 **微内核 + 事件总线** 架构，参考 Moltbot 设计：

```
┌─────────────────────────────────────────────────────────┐
│                    Gateway (运行平台)                     │
│  - WebSocket/HTTP 协议处理                                │
│  - EventEmitter (事件总线)                                │
│  - ConnectionManager (连接管理)                          │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ ToolService  │  │MemoryService │  │Conversation  │
│  (工具服务)  │  │ (记忆服务)   │  │  Service     │
│              │  │              │  │ (对话服务)   │
└──────────────┘  └──────────────┘  └──────────────┘
```

## 核心流程

### 1. 消息接收流程

```
Channel 收到消息
    │
    ▼
GatewayIntegration._handle_incoming_message()
    │
    ▼
发出 CHANNEL_MESSAGE 事件 (EventEmitter)
    │
    ├─────────────────┬─────────────────┐
    ▼                 ▼                 ▼
MemoryService    ConversationService  其他订阅者
订阅事件        订阅事件
自动保存记忆    处理对话流程
```

### 2. 记忆处理流程

```
CHANNEL_MESSAGE 事件
    │
    ▼
MemoryService._on_channel_message()
    │
    ├─ 保存用户消息到记忆系统
    ├─ 触发记忆维护（聚类/摘要/衰减）
    └─ 发出 MEMORY_SAVED 事件
```

### 3. 对话处理流程

```
CHANNEL_MESSAGE 事件
    │
    ▼
ConversationService._on_channel_message()
    │
    ├─ 发出 CONVERSATION_START 事件
    ├─ 获取历史消息（MessageManager）
    ├─ 召回记忆上下文（MemoryService.get_context）
    ├─ 构建系统提示词（含记忆）
    ├─ 调用 LLM（PrometheaConversation.run_chat_loop）
    │   └─ 工具调用循环（ToolService）
    ├─ 保存回复到历史
    ├─ 保存回复到记忆
    └─ 发出 CONVERSATION_COMPLETE 事件（含回复内容）
    │
    ▼
GatewayIntegration._on_conversation_complete()
    │
    └─ 发送回复给渠道
```

### 4. 工具调用流程

```
LLM 输出工具调用请求
    │
    ▼
ToolService.call_tool()
    │
    ├─ 发出 TOOL_CALL_START 事件
    ├─ 调用 MCPManager.unified_call()
    ├─ 发出 TOOL_CALL_RESULT 事件
    └─ 返回结果给对话循环
```

## 事件总线事件类型

### 通道事件
- `CHANNEL_MESSAGE`: 通道收到消息

### 记忆事件
- `MEMORY_SAVED`: 记忆已保存
- `MEMORY_RECALLED`: 记忆已召回
- `MEMORY_CLUSTERED`: 记忆已聚类
- `MEMORY_SUMMARIZED`: 记忆已摘要

### 对话事件
- `CONVERSATION_START`: 对话开始
- `CONVERSATION_COMPLETE`: 对话完成（含回复内容）
- `CONVERSATION_ERROR`: 对话错误

### 工具事件
- `TOOL_CALL_START`: 工具调用开始
- `TOOL_CALL_RESULT`: 工具调用结果
- `TOOL_CALL_ERROR`: 工具调用错误

## 服务层设计

### ToolService
- **职责**: 统一工具调用接口
- **依赖**: EventEmitter, MCPManager
- **功能**: 工具注册/查询/调用，发出工具生命周期事件

### MemoryService
- **职责**: 记忆系统服务层
- **依赖**: EventEmitter, MemoryAdapter
- **功能**: 自动保存/召回记忆，记忆维护（聚类/摘要/衰减），发出记忆事件

### ConversationService
- **职责**: 对话系统服务层
- **依赖**: EventEmitter, PrometheaConversation, MemoryService, MessageManager
- **功能**: 自动处理对话流程，发出对话事件

## 设计原则

1. **Gateway 只做平台 + 事件总线**：不直接依赖具体实现
2. **服务层通过事件总线通信**：解耦，便于扩展
3. **保留原有功能逻辑**：服务层只是封装，不重写
4. **向后兼容**：保留旧属性名，逐步迁移
