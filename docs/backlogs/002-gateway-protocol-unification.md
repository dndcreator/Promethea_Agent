# Backlog 002 - Gateway Protocol 统一化

## 1. 背景

Promethea 当前已经形成 gateway-first 的整体方向，并且已经具备 `gateway/server.py`、`gateway/protocol.py`、`conversation_service`、`memory_service`、`tool_service` 等关键边界。

但现阶段 Gateway 仍更像“组织良好的服务集合”，而不是拥有统一协议契约的控制平面。不同入口、不同 service、不同事件之间虽然在逻辑上相关，但缺少一套明确、稳定、结构化的协议层来统一：

- 输入如何进入 Runtime
- 中间结果如何在 service 之间流转
- 工具 / 记忆 / 推理结果如何被表达
- 事件如何被序列化与追踪
- 响应如何被统一返回

本任务的目标是：**把 Gateway Protocol 从隐含约定升级为显式契约**。

---

## 2. 目标

本任务要完成：

1. 明确 Gateway 层的统一协议对象
2. 让不同入口共享同一种 request / response 语义
3. 让关键 service 之间通过统一结构传递数据
4. 为 trace、audit、inspector、workflow replay 打基础
5. 降低未来新增 channel / desktop / workflow / skill 时的耦合成本

---

## 3. 非目标

本任务不负责：

- 重写全部 gateway 实现
- 一次性重构所有 service 内部逻辑
- 完整实现 workflow protocol
- 完整实现 websocket / streaming protocol 细节
- 替换所有旧对象

本任务重点是建立 **协议骨架**，并在关键路径先接入。

---

## 4. 当前代码位置

优先检查以下模块：

- `gateway/protocol.py`
- `gateway/server.py`
- `gateway/events.py`
- `gateway/conversation_service.py`
- `gateway/memory_service.py`
- `gateway/tool_service.py`
- `gateway/reasoning_service.py`

如果 HTTP 入口、message manager、response builder 等逻辑散落在其他模块，也需要纳入梳理范围。

---

## 5. 设计目标

Gateway Protocol 需要承担以下角色：

1. **统一入口契约**
   - 所有入口都能转换为统一 `GatewayRequest`

2. **统一运行契约**
   - Runtime 内部模块共享统一上下文对象和结果对象

3. **统一事件契约**
   - 所有关键动作都能产生标准化事件

4. **统一输出契约**
   - 所有响应都能被统一表达为 `GatewayResponse`

5. **统一追踪契约**
   - 所有对象都能挂接 `trace_id / session_id / user_id / request_id`

---

## 6. 建议协议对象

## 6.1 GatewayRequest

表示入口层进入 Gateway 的统一请求对象。

建议字段：

- `request_id`
- `trace_id`
- `session_id`
- `user_id`
- `agent_id`
- `channel_id`
- `input_text`
- `input_payload`
- `attachments`
- `metadata`
- `requested_mode`
- `requested_skill`
- `requested_workflow`
- `debug_flags`

说明：

- Web、HTTP、Desktop、Telegram 等入口都应转为该对象
- 不同入口可以保留自己的适配层，但不能绕开该对象直接进入核心 runtime

---

## 6.2 GatewayResponse

表示 Runtime 输出给入口层的统一响应对象。

建议字段：

- `request_id`
- `trace_id`
- `session_id`
- `user_id`
- `response_text`
- `response_blocks`
- `artifacts`
- `tool_summary`
- `reasoning_summary`
- `memory_write_summary`
- `status`
- `error`
- `metrics`

说明：

- 入口层只负责把 `GatewayResponse` 映射到 UI / HTTP / IM 的具体输出形式
- 不应在出口层重新组织复杂业务逻辑

---

## 6.3 GatewayEvent

表示运行过程中的标准事件。

建议字段：

- `event_id`
- `event_type`
- `trace_id`
- `request_id`
- `session_id`
- `user_id`
- `timestamp`
- `source_module`
- `payload`
- `severity`
- `tags`

说明：

- 所有事件必须是结构化对象
- 事件名必须集中维护，不允许自由散落

---

## 6.4 Service Input / Output 协议对象

建议为主要 service 定义明确输入输出对象，例如：

### conversation service

- `ConversationRunInput`
- `ConversationRunOutput`

### memory service

- `MemoryRecallRequest`
- `MemoryRecallResult`
- `MemoryWriteRequest`
- `MemoryWriteDecision`

### tool service

- `ToolExecutionRequest`
- `ToolExecutionResult`

### reasoning service

- `ReasoningRequest`
- `ReasoningResult`

说明：

- 第一阶段不必全量引入复杂 schema，但至少先固定对象名称与方向
- 内部可以逐步替换旧参数列表

---

## 7. 协议分层原则

## 7.1 入口协议与内部协议分开

- `GatewayRequest / GatewayResponse` 面向边界层
- service input/output 面向内部模块

不要把边界层对象直接塞到所有模块内部当万能对象。

---

## 7.2 协议对象要稳定

协议对象命名和字段应尽量稳定，避免频繁改动导致后续 channel / workflow / inspector 不断跟着变。

---

## 7.3 协议要可序列化

所有关键对象都应可 JSON 序列化，方便：

- 调试
- trace
- audit
- inspector
- workflow replay
- 快照落盘

---

## 7.4 协议字段要有边界

协议对象不是“什么都塞进去的大包”。字段设计必须围绕职责，避免无限膨胀。

---

## 8. 推荐事件类型（第一轮）

建议统一以下基础事件：

- `gateway.request.received`
- `gateway.run.started`
- `conversation.run.started`
- `memory.recall.started`
- `memory.recall.finished`
- `reasoning.started`
- `reasoning.finished`
- `tool.execution.started`
- `tool.execution.finished`
- `tool.execution.failed`
- `response.synthesized`
- `memory.write.decided`
- `gateway.run.finished`

这些事件建议集中定义在一个文件中，例如：

- `gateway/event_types.py`

---

## 9. 推荐实现路径

## 9.1 第一步：明确 protocol 模块结构

建议在 `gateway/protocol.py` 基础上整理为更清晰结构。可选方案：

### 方案 A：单文件
- `gateway/protocol.py`

### 方案 B：拆目录
- `gateway/protocol/__init__.py`
- `gateway/protocol/request.py`
- `gateway/protocol/response.py`
- `gateway/protocol/events.py`
- `gateway/protocol/service_io.py`

若当前项目还处于快速演进期，优先选单文件或轻量拆分，不必过早复杂化。

---

## 9.2 第二步：先接入入口层与出口层

优先改造：

- request 进入 server/gateway 时创建 `GatewayRequest`
- response 输出前统一为 `GatewayResponse`

这样可以最小成本把边界先定住。

---

## 9.3 第三步：让核心 service 逐步切换到结构化 I/O

优先改造：

- conversation service
- memory service
- tool service
- reasoning service

要求：

- 新逻辑优先走结构化协议对象
- 老逻辑可以暂时通过 adapter 兼容

---

## 9.4 第四步：事件标准化

所有关键路径统一发 `GatewayEvent`，用于后续：

- trace
- audit
- session inspector
- workflow replay

---

## 10. 测试要求

至少需要补以下测试：

1. `GatewayRequest` 序列化测试
2. `GatewayResponse` 序列化测试
3. `GatewayEvent` 序列化测试
4. server 入口构建 `GatewayRequest` 的测试
5. response builder /出口层使用 `GatewayResponse` 的测试
6. 至少一个 service input/output 协议对象的接入测试

---

## 11. 验收标准

本任务完成后，必须满足：

- 已存在统一的 `GatewayRequest`
- 已存在统一的 `GatewayResponse`
- 已存在统一的 `GatewayEvent`
- 入口层至少一条主路径已使用 `GatewayRequest`
- 出口层至少一条主路径已使用 `GatewayResponse`
- 至少一个 service 已开始使用结构化 I/O 对象
- 事件体系已集中定义基础事件名

---

## 12. 风险与注意事项

### 风险 1：协议设计过重
第一版不要追求一步到位的大而全协议系统。重点是建立稳定骨架，而不是过度抽象。

### 风险 2：边界不清导致协议对象泛滥
必须区分：
- 边界请求/响应对象
- 内部 service I/O 对象
- 事件对象

不要把三者混成一种。

### 风险 3：旧逻辑完全推翻
允许第一阶段保留 adapter / bridge 层，不要求旧逻辑一次性完全删除。

---

## 13. 回滚方案

如接入后影响过大，应允许：

- 保留新的协议对象定义
- 入口/出口层继续使用协议对象
- service 内部短期通过 adapter 兼容旧参数模式

不允许回滚到“没有统一协议对象”的状态。

---

## 14. 完成后应追加的文档更新

任务完成后，需要同步更新：

- `docs/architecture/runtime-overview.md`
- `docs/architecture/gateway-protocol.md`（建议新增）
- `docs/adr/ADR-002-gateway-protocol.md`（建议新增）

---

## 15. 建议提交信息

可参考：

- `feat(gateway): introduce unified gateway protocol objects`
- `refactor(protocol): standardize request response and event schema`
