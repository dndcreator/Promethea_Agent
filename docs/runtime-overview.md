# Promethea Runtime Overview

## 1. 文档目的

本文档描述 Promethea Runtime 的整体结构、关键对象、运行链路与模块职责。它是工程师与 Codex 理解系统运行机制的入口文档。

阅读顺序建议：

1. 本文档
2. `promethea_long_term_engineering_plan.md`
3. `gateway-protocol.md`
4. `memory-model.md`
5. `tool-runtime.md`
6. `reasoning-model.md`

---

## 2. Runtime 总体定义

Promethea Runtime 是系统的统一执行环境，负责将来自不同入口的用户输入，转化为带有上下文、记忆、工具、推理与审计能力的一次完整运行。

Runtime 的目标不是单纯生成回复，而是：

- 维护用户边界
- 维护会话状态
- 召回合适记忆
- 在策略约束下使用工具
- 在需要时执行显式推理
- 合成输出
- 写入可治理的运行结果
- 为后续恢复、追踪和审计提供结构化痕迹

---

## 3. Runtime 的层次结构

Promethea Runtime 可以理解为以下 5 个核心层协作的结果：

### 3.1 Interface Layer

负责接收输入与输出结果，包括：

- Web UI
- HTTP API
- Desktop / Tauri
- 后续 IM 渠道

接口层不负责核心业务决策，只负责将输入交给 Gateway。

### 3.2 Gateway Control Plane

Gateway 是 Runtime 的控制中枢，负责：

- 构建运行上下文
- 管理会话
- 调度各服务
- 发出事件
- 记录 trace / audit
- 协调 tools / memory / reasoning

### 3.3 Runtime Pipeline

Runtime Pipeline 表示单次运行的核心流程，至少包括：

1. Input Normalization
2. Mode Detection
3. Memory Recall
4. Planning / Reasoning
5. Tool Execution
6. Response Synthesis

### 3.4 Capability Layers

为 Runtime 提供能力来源：

- Memory
- Tools / MCP
- Skills
- Workspace
- Workflow
- Reasoning

### 3.5 Security / Observability Layer

为 Runtime 提供边界与可见性：

- namespace isolation
- tool policy
- trace
- audit
- doctor
- config validation

---

## 4. 核心运行对象

## 4.1 SessionState

`SessionState` 表示一个会话级对象，用于记录会话长期状态。

生命周期：
- 长于单轮请求
- 可跨多轮运行复用
- 由 Gateway 管理

典型字段：
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

---

## 4.2 RunContext

`RunContext` 表示一次具体运行所使用的统一上下文。

生命周期：
- 从接收到请求开始
- 到本次运行结束为止
- 不应被多个无关请求复用

典型内容：
- 当前 `SessionState`
- 输入内容
- Prompt Blocks
- Memory Recall Bundle
- Tool Availability / Policy
- Reasoning State
- Workspace Handle
- Budget / Trace / Debug 信息

---

## 4.3 GatewayRequest / GatewayResponse

所有入口都应将输入封装为统一请求结构，并由 Gateway 返回统一响应结构。

这样做的目的：

- 降低多入口对核心逻辑的侵入
- 让 Web / HTTP / Desktop / IM 共享 Runtime 语义
- 让 Inspector / Replay / Audit 使用统一数据模型

---

## 5. 单次运行的标准流程

下面是一轮标准运行的目标流程。

## 5.1 Step 1 - Input Normalization

负责：

- 标准化输入格式
- 提取用户、会话、渠道等元数据
- 生成或绑定 `trace_id`
- 建立 `RunContext`

输出：
- `NormalizedInput`
- 初始化后的 `RunContext`

---

## 5.2 Step 2 - Mode Detection

负责判断本轮运行应采用的模式，例如：

- fast
- deep
- workflow

判断依据可以包括：

- 用户显式指令
- 历史会话状态
- 当前工具/记忆需求
- 风险与预算约束

输出：
- `ModeDecision`

---

## 5.3 Step 3 - Memory Recall

负责：

- 根据当前输入与会话状态召回相关记忆
- 区分 working / episodic / semantic / profile / reasoning template memory
- 附带 recall reason、来源、置信度

输出：
- `MemoryRecallBundle`

---

## 5.4 Step 4 - Planning / Reasoning

负责：

- 判断是否需要显式规划
- 在需要时构建 reasoning tree / planner state
- 决定是否需要工具调用或继续细分步骤

输出：
- `PlanResult`
- 或更新后的 `ReasoningState`

---

## 5.5 Step 5 - Tool Execution

负责：

- 根据 ToolSpec / ToolPolicy 调用允许的工具
- 统一处理输入输出
- 规范化结果
- 记录 trace / audit

输出：
- `ToolExecutionBundle`

---

## 5.6 Step 6 - Response Synthesis

负责：

- 综合输入、记忆、工具结果、推理结果
- 生成用户可见回复
- 产出 workspace artifact（如适用）
- 决定是否触发 memory write gate

输出：
- `ResponseDraft`
- `FinalResponse`

---

## 6. Runtime 的核心模块职责

## 6.1 gateway

负责控制平面逻辑，不负责承载所有业务细节。

核心职责：

- 建立 `RunContext`
- 调用 pipeline
- 发事件
- 汇总 trace
- 统一输出

## 6.2 conversation_service

负责单轮对话运行的主要编排，是 pipeline 的主要承载者之一。

## 6.3 memory_service

负责记忆召回、写入前判断、记忆层路由、后续治理接口。

## 6.4 tool_service

负责工具注册、策略检查、执行协调、结果规范化。

## 6.5 reasoning_service

负责 planning、reasoning node 管理、verifier、workflow-compatible state。

## 6.6 mcp_manager

负责外部 MCP 服务接入、工具目录同步、工具调用桥接。

---

## 7. Runtime 的设计边界

## 7.1 Runtime 不等于 UI

UI 只是入口和展示层，不是系统本体。

## 7.2 Runtime 不等于单轮 Prompt

Prompt 只是 Runtime 的一个组成部分，不应被视为全部控制手段。

## 7.3 Runtime 不等于工具集合

工具只是能力来源之一；真正重要的是上下文、策略、推理和边界。

## 7.4 Runtime 不等于数据库

存储是底层能力，不等于 Runtime 语义本身。

---

## 8. Runtime 设计原则

### 8.1 显式上下文优先
所有核心模块都应显式接受 `RunContext` 或其等价对象。

### 8.2 单一运行链路可追踪
一次运行必须能通过 `trace_id` 完整追踪。

### 8.3 用户边界优先
所有运行对象都必须显式携带 `user_id` 或与其绑定。

### 8.4 结构化优先于 Prompt Patch
优先通过 schema、policy、state machine 修复系统问题，而不是堆提示词。

### 8.5 可恢复性优先
后续所有复杂能力都要考虑 workflow / recovery 兼容性。

---

## 9. 后续配套文档

本文件是总览，后续应配套以下文档：

- `gateway-protocol.md`
- `memory-model.md`
- `tool-runtime.md`
- `reasoning-model.md`
- `workspace-model.md`
- `workflow-model.md`

---

## 10. 当前建议的下一步任务

建议在完成本文件后，优先推进以下任务：

1. `001-runcontext-and-sessionstate.md`
2. `002-gateway-protocol-unification.md`
3. `003-conversation-pipeline-staging.md`

这些任务完成后，Promethea Runtime 才真正具备统一演进的基础。

---

## 11. Prompt Assembly (Backlog 004)

Runtime prompt construction adopts a block-based assembly model:

- typed prompt blocks (`identity`, `policy`, `memory`, `tools`, `workspace`, `reasoning`, `response_format`)
- assembler-driven ordering, token estimation, and optional compaction
- debug metadata attached to runtime output (`prompt_assembly`) and `RunContext.prompt_blocks`

Primary implementation lives in:

- `gateway/prompt_blocks.py`
- `gateway/prompt_assembler.py`
- `gateway/conversation_pipeline.py`

---

## 12. Tool Governance (Backlog 005)

Runtime tool governance uses three explicit layers:

- `ToolSpec`: canonical tool metadata and risk descriptors
- `ToolRegistry`: unified local + MCP tool registry
- `ToolPolicy`: runtime policy checks with side-effect-safe defaults

`ToolService.call_tool` performs registry resolution and policy evaluation in runtime paths carrying `RunContext`.

---

## 13. Observability Foundation (Backlog 006)

Runtime event bus now keeps structured in-memory histories for:

- trace events (`TraceEvent`)
- audit events (`AuditEvent`)

This provides minimal query helpers and a stable schema baseline for inspector/doctor expansion.

## 14. Memory Write Gate (Backlog 007)

Runtime memory persistence now uses an explicit write gate before long-term writes:

- request contract: `MemoryWriteRequest`
- decision contract: `MemoryWriteDecision`
- decision statuses: `allow | deny | defer`

The gateway emits `memory.write.decided` for each candidate with reason and target layer.

## 15. Reasoning Node State Machine (Backlog 008)

Reasoning nodes now use explicit lifecycle states and transition rules.

- unified node states: `pending/running/waiting_tool/waiting_human/succeeded/failed/skipped`
- explicit transition validation in runtime
- step execution path integrated with waiting-tool and waiting-human recovery primitives

## 16. Workspace Sandbox MVP (Backlog 009)

Runtime now supports a bounded workspace artifact path:

- workspace handle resolution on run context
- sandboxed artifact write/update/list/snapshot
- write and blocked-write events are trace/audit visible

## 17. MCP Health And Tool Panel Foundation (Backlog 010)

Runtime MCP layer now provides structured health and panel-facing tool metadata:

- service health snapshots (`online/offline/degraded`) with last sync/error info
- normalized MCP tool descriptors for inspection and UI panel feeds
- user visibility filtering for tool list queries

Gateway query methods:

- `mcp.services.list`
- `mcp.service.health`
- `mcp.service.tools`
- `mcp.tools.visible`

## 18. Memory Recall Policy And Inspector (Backlog 011)

Memory recall now uses a structured request/result contract instead of opaque context-only retrieval.

- mode-aware recall policy (`fast/deep/workflow`)
- selected-item recall reasons and source-layer metadata
- dropped-candidate reasons for inspector/debug
- recall run inspector queries via gateway and HTTP

## 19. Workflow Engine MVP (Backlog 012)

Backlog 012 adds a linear, resumable workflow runtime with these components:

- schema: `WorkflowDefinition`, `WorkflowRun`, `WorkflowStep`, `Checkpoint`
- engine: `gateway/workflow_engine.py`
- protocol methods: `workflow.*`
- HTTP routes: `/workflow/*`

The engine supports:

- start / pause / resume
- retry failed step
- human approval gate (`approval_step`)
- checkpoint capture on step boundaries
- artifact output into workspace sandbox

This forms the minimum recoverable execution backbone for long-running tasks while keeping scope constrained to linear workflows.

## 20. Channel Adapter Framework (Backlog 013)

Backlog 013 introduces a channel adapter layer that normalizes channel-specific input/output to gateway contracts.

Delivered:

- unified adapter interface and metadata model
- adapter registry with default channels (`web`, `http_api`, `telegram`)
- chat entry in gateway server now resolves adapter for identity normalization, permission check, and request/response mapping
- HTTP non-stream chat path now routes through `http_api` adapter mapping

This reduces channel/runtime coupling and provides a stable path for adding desktop/IM/voice channels.

## 21. Skill Layer and Official Packs (Backlog 014)

Backlog 014 introduces a formal Skill Layer to package task capability into structured units.

Implemented components:
- `skills/schema.py` with `SkillSpec`, `SkillExample`, `SkillEvaluationCase`
- `skills/registry.py` for official pack loading and user-aware skill resolution
- official pack scaffold under `skills/packs/official/coding_copilot`

Runtime effects:
- chat turn builds `RunContext` and binds effective skill
- skill `tool_allowlist` is injected into run-context policy
- skill `default_mode` is applied when request mode is absent
- skill `system_instruction` is merged into conversation system prompt
- prompt assembler now supports skill block and prompt block policy filtering

HTTP effects:
- `/api/skills/catalog`
- `/api/skills/{skill_id}`
- `/api/skills/install`
- `/api/skills/activate`
- `/api/chat` supports `requested_skill` and `requested_mode`

## 22. Config Schema and Migration Governance (Backlog 015)

Backlog 015 introduces a minimal configuration governance baseline.

Implemented:
- `config_version` root marker (default `1`)
- migration module: `gateway/config_migrations.py`
- deprecation warning collection in `ConfigService`
- scoped config access methods in `ConfigService`

Scoped access APIs:
- `get_runtime_config(user_id, scope=...)`
- `get_user_preferences(user_id, scope=...)`
- `get_tool_policy_config(user_id, agent_id)`
- `get_channel_config(channel_id, user_id)`

HTTP additions:
- `GET /api/config/runtime/scoped`
- `GET /api/config/preferences`
- `GET /api/config/tool-policy`
- `GET /api/config/channel/{channel_id}`

Compatibility:
- legacy keys remain readable
- migration populates boundary sections without hard-breaking existing callers

## 23. Namespace And Security Audit Foundation (Backlog 016)

Backlog 016 establishes an auditable multi-user boundary baseline.

Implemented:

- explicit namespace violation event type: `security.boundary.violation`
- security audit report builder: `gateway/security/audit.py`
- HTTP security audit APIs:
  - `GET /api/security/audit/report`
  - `GET /api/security/audit/events`
- boundary enforcement points in runtime:
  - memory recall namespace mismatch emits security violation events
  - workspace access asserts owner/requester match
  - tool execution enforces run-context and invocation identity boundary

This turns namespace isolation from design intent into enforceable and inspectable runtime behavior.
