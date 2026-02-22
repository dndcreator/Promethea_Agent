# Gateway Module

---

## 中文文档

### 1. 这个模块是做什么的

`gateway` 是系统运行时中枢，负责把各子系统串成一条稳定链路：
- 接请求
- 调服务
- 管状态
- 回响应

它的职责是“编排”，不是“所有业务细节都写在这里”。

### 2. 包含哪些关键文件

- `gateway/app.py`：网关生命周期与初始化顺序
- `gateway/server.py`：网关主服务与核心处理入口
- `gateway/config_service.py`：配置读取、合并、更新、重置
- `gateway/conversation_service.py`：会话与对话编排
- `gateway/memory_service.py`：记忆服务接入层
- `gateway/tool_service.py`：工具调用协调层
- `gateway/events.py`：事件总线
- `gateway/protocol.py`：协议数据结构
- `gateway/connection.py`：连接管理辅助

### 3. 架构设计与工作流

标准流：

1. 请求进入 HTTP 路由层
2. 进入 gateway service（配置/会话/工具/记忆）
3. 服务间通过统一协议传递数据
4. 产出响应并记录日志/指标

设计重点：
- 服务边界清晰（Config/Conversation/Memory/Tool）
- 用户上下文贯穿全链路
- 支持后续替换单个子服务而不推翻整体

### 4. 一个简单例子

用户点“保存设置”：

1. 前端发 `POST /api/config/update`
2. 路由把请求交给 `ConfigService`
3. `ConfigService` 做合并和校验
4. 持久化到用户配置文件
5. 返回成功并让前端更新状态

### 5. 使用注意事项

- 配置更新尽量走单入口，避免双写冲突
- 不要在 Route 层写太多业务逻辑
- 用户隔离逻辑不能省略（必须带 `user_id`）

### 6. 修改注意事项

- 新增能力优先放到对应 service，再由 route 调用
- 改协议字段时同步更新前端和测试
- 改会话处理时回归 `tests/test_message_manager_turns.py`

---

## English Documentation

### 1. Purpose

`gateway` is the runtime orchestrator. It wires all major subsystems together:
- receive requests
- call services
- manage state
- return normalized responses

Its job is orchestration, not storing every business detail in one place.

### 2. Key Files

- `gateway/app.py`: lifecycle and startup order
- `gateway/server.py`: main server orchestration entry
- `gateway/config_service.py`: config merge/update/reset
- `gateway/conversation_service.py`: conversation/session orchestration
- `gateway/memory_service.py`: memory integration façade
- `gateway/tool_service.py`: tool-call coordination
- `gateway/events.py`: event bus
- `gateway/protocol.py`: protocol data structures
- `gateway/connection.py`: connection helpers

### 3. Architecture & Flow

1. Request enters HTTP routes
2. Routed to gateway services
3. Data moves through stable protocol shapes
4. Response is returned with logging/metrics

Design principles:
- clear service boundaries
- user context across the full path
- replaceable internals with stable external behavior

### 4. Simple Example

Settings save flow:

1. UI calls `POST /api/config/update`
2. Route delegates to `ConfigService`
3. `ConfigService` validates + merges updates
4. Persists into user config file
5. Returns success for UI state refresh

### 5. Operational Notes

- Prefer single update path for config writes
- Keep route layer thin
- Never bypass `user_id`-based isolation checks

### 6. Change Notes

- Add new features in service layer first, then expose via routes
- When protocol fields change, sync frontend and tests
- Re-run turn/session regression tests after conversation changes
