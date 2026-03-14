# Backlog 001 - RunContext 与 SessionState 统一化

## 1. 背景

Promethea 当前已经具备 `gateway`、`conversation_service`、`memory_service`、`tool_service`、`reasoning_service` 等核心模块，但运行时上下文仍未完全统一。不同模块之间虽然已经有清晰边界，但一次完整运行所依赖的“共享状态对象”仍不够显式，导致以下问题：

- 新增入口时容易重复组装上下文
- 会话、工具、记忆、推理之间的状态流转不够统一
- trace / audit / replay 的基础对象不完整
- Workflow / Workspace / Multi-agent 等后续能力缺少可复用运行时底座

本任务是长期主计划的第一项基础任务，负责为后续 Gateway Control Plane、Pipeline、Reasoning、Memory、Workflow 等能力提供统一上下文模型。

---

## 2. 目标

本任务的目标是：

1. 定义统一的 `SessionState`
2. 定义统一的 `RunContext`
3. 明确两者与现有 gateway / conversation / memory / tool / reasoning 模块的关系
4. 为后续 trace / audit / workflow / workspace 提供统一挂载点
5. 在不大面积破坏现有代码的前提下完成第一轮接入

---

## 3. 非目标

本任务不负责：

- 完整重写全部 gateway 服务
- 一次性完成所有 service 的彻底重构
- 引入完整 workflow engine
- 修改业务逻辑本身
- 解决所有历史技术债

本任务重点是**建立统一运行时对象模型**，而不是一口气重构全系统。

---

## 4. 当前代码位置

重点关注以下现有模块：

- `gateway/server.py`
- `gateway/protocol.py`
- `gateway/conversation_service.py`
- `gateway/memory_service.py`
- `gateway/tool_service.py`
- `gateway/reasoning_service.py`
- `gateway/events.py`

如果项目中存在与 session / message manager / request context 相关的模块，也应一并检查并纳入适配范围。

---

## 5. 目标设计

## 5.1 SessionState

`SessionState` 表示一次会话实例的统一状态对象。

建议字段至少包括：

- `session_id`
- `user_id`
- `agent_id`
- `channel_id`
- `workspace_id`
- `memory_scope`
- `tool_policy_profile`
- `reasoning_mode`
- `trace_id`
- `status`
- `created_at`
- `updated_at`

建议增加的扩展字段：

- `session_metadata`
- `last_user_message_at`
- `last_assistant_message_at`
- `active_workflow_id`
- `active_skill_id`
- `tags`

---

## 5.2 RunContext

`RunContext` 表示一次具体运行（run）所使用的统一执行上下文。

建议字段至少包括：

- `session_state`
- `request_id`
- `user_identity`
- `agent_persona`
- `input_payload`
- `normalized_input`
- `memory_bundle`
- `tool_availability`
- `tool_policy`
- `reasoning_state`
- `prompt_blocks`
- `token_budget`
- `cost_budget`
- `workspace_handle`
- `event_buffer`
- `debug_flags`

建议扩展字段：

- `skill_context`
- `workflow_context`
- `audit_context`
- `safety_context`
- `runtime_notes`

---

## 5.3 关系定义

### SessionState 与 RunContext 的关系

- `SessionState` 是会话级对象，生命周期长于单次运行
- `RunContext` 是运行级对象，生命周期只覆盖单轮请求或单次任务执行
- 一个 `SessionState` 可以产生多个 `RunContext`

### 与 Gateway 的关系

- 所有入口最终都要构造 `RunContext`
- `server.py` 或 gateway 接入层负责初始化 `RunContext`
- 各 service 不应自行发明新的上下文容器

### 与 Trace / Audit 的关系

- `trace_id` 必须同时出现在 `SessionState` 和 `RunContext`
- 所有关键事件都应能通过 `RunContext` 追溯
- `RunContext` 应是 audit 记录的基础关联对象

---

## 6. 建议实现路径

## 6.1 第一步：定义数据模型

建议新增：

- `gateway/models/session_state.py`
- `gateway/models/run_context.py`

或等价位置的 schema/model 文件。

要求：

- 模型字段明确
- 支持序列化
- 支持日志输出
- 支持后续扩展
- 命名稳定，不要频繁变更

如项目已有统一 schema/model 层，可复用现有组织方式。

---

## 6.2 第二步：在 gateway 入口层初始化 RunContext

入口层至少要做到：

1. 从 request 中提取 `user_id`
2. 确定 `session_id`
3. 生成或传递 `trace_id`
4. 构建 `SessionState`
5. 构建 `RunContext`
6. 将 `RunContext` 传入 conversation pipeline

注意：

- 入口层只负责初始化，不负责承载业务逻辑
- 不要在入口层拼接大量 prompt 或工具逻辑

---

## 6.3 第三步：让核心 service 接口显式接收 RunContext

优先改造以下 service：

- `conversation_service`
- `memory_service`
- `tool_service`
- `reasoning_service`

至少第一轮要做到：

- service 接口可以接收 `RunContext`
- 核心日志和事件能引用 `RunContext`
- 不强求第一版所有内部逻辑完全改造，但新逻辑必须优先使用 `RunContext`

---

## 6.4 第四步：事件体系接入

在 `gateway/events.py` 或等价模块中，确保所有关键事件能携带：

- `trace_id`
- `session_id`
- `user_id`
- `request_id`

后续 trace / inspector / workflow replay 都依赖这一点。

---

## 7. 推荐事件类型

第一轮建议统一以下事件：

- `session.started`
- `run.started`
- `input.normalized`
- `memory.recall.started`
- `memory.recall.finished`
- `tool.execution.started`
- `tool.execution.finished`
- `tool.execution.failed`
- `reasoning.started`
- `reasoning.finished`
- `response.synthesized`
- `run.finished`

要求事件名集中定义，不允许到处自由拼字符串。

---

## 8. 测试要求

至少补以下测试：

1. `SessionState` 创建测试
2. `RunContext` 创建测试
3. gateway 入口构建 `RunContext` 测试
4. `RunContext` 传入 conversation service 的测试
5. 关键事件包含 `trace_id/session_id/user_id` 的测试

如项目已有测试目录和测试风格，沿用原风格即可。

---

## 9. 验收标准

本任务完成后，必须满足：

- 已存在统一 `SessionState`
- 已存在统一 `RunContext`
- gateway 入口层能创建并传递 `RunContext`
- conversation pipeline 至少第一层已经使用 `RunContext`
- 至少 memory/tool/reasoning 三类关键事件能携带统一追踪字段
- 文档中已记录模型字段与职责边界

---

## 10. 风险与注意事项

### 风险 1：一次性改太多模块
本任务是基础设施任务，不应一次性重写所有逻辑。应优先完成“接入”和“挂载”，再逐步内化。

### 风险 2：RunContext 变成万能垃圾袋
`RunContext` 应保持“运行所需上下文”的定位，不要把所有内容都塞进去。后续新增字段要经过 ADR 或明确文档说明。

### 风险 3：SessionState 与持久层强耦合
第一版不要求 `SessionState` 直接绑定数据库表设计。先以运行时模型为主，持久化策略后续再细化。

---

## 11. 回滚方案

如果接入过程中对现有逻辑影响过大，应允许以下回滚：

- 保留新模型文件
- 暂时只在 gateway 入口层创建 `RunContext`
- service 内部继续兼容旧参数模式
- 通过 adapter/bridge 逐步完成切换

不允许因为回滚而删除统一模型定义本身。

---

## 12. 完成后应追加的文档更新

任务完成后，需要同步更新：

- `docs/architecture/runtime-overview.md`
- `docs/architecture/gateway-protocol.md`（如已存在）
- `docs/adr/ADR-001-runcontext.md`（建议新增）

---

## 13. 建议提交信息

可参考：

- `feat(runtime): introduce SessionState and RunContext`
- `refactor(gateway): pass RunContext through conversation pipeline`
