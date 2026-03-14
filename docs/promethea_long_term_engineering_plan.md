# Promethea 长期工程主计划（面向工程师与 Codex）

## 0. 文档定位

本文档是 Promethea 的长期执行主计划。它整合此前多轮方案中的有效内容，删除评论性表述，保留以下内容：

- 目标与对标关系
- 当前项目基础与差距
- 长期架构蓝图
- 分 Workstream 的实施计划
- 预期效果与验收标准
- 工程文档体系与 Codex 长期协作规范
- 里程碑与优先级

本文档的用途不是做宣讲，而是作为长期工程主文件使用。后续迭代以本文档为基线，通过 ADR、Backlog Task、模块文档、接口文档进行增量维护。

---

## 1. 总体目标

### 1.1 北极星目标

Promethea 的北极星不是“接入更多渠道”或“做一个聊天机器人”，而是：

**构建一个 memory-native、reasoning-aware、multi-user-safe 的 agent runtime，使 agent 能在长期、多轮、多任务环境中稳定记住用户、规划行动、调用能力、交付结果，并可持续恢复。**

### 1.2 产品定义

Promethea 最终应被定义为：

**一个面向个人与小团队的 agent runtime / agent OS 基础设施**，具备：

- 统一控制平面
- 统一运行时上下文
- 统一记忆层
- 统一工具与技能层
- 统一工作区
- 统一审计、诊断与恢复能力
- 安全的多用户隔离能力

### 1.3 对标策略

#### 需要追赶 OpenClaw 的部分

- Gateway 作为单一控制平面
- 结构化的工具与协议治理
- Runtime 层的诊断与审计
- 渠道接入框架
- Workspace / Canvas 类工作区能力
- Skills 的产品化组织方式
- 安全基线与配置治理

#### 必须保留并强化的 Promethea 特色

- 多用户隔离与命名空间边界
- Hot / Warm / Cold 分层记忆
- User-scoped memory ownership
- Prompt Assembly 主权
- 显式 Reasoning Tree / Planner
- Reasoning Outcome Gate
- 可恢复工作流
- 面向长期协作的项目级记忆与画像能力

---

## 2. 现状归纳与方向判断

### 2.1 Promethea 当前已有的正确基础

Promethea 当前已经形成以下核心基础：

- `gateway` 被定义为运行时中枢，而不是简单 API 层。
- 系统已经拆出 `config_service`、`conversation_service`、`memory_service`、`tool_service` 等边界。
- 设计原则已明确包含多用户隔离、分层记忆、策略化工具访问、Reasoning Outcome Gate。
- 已存在 `reasoning_service.py`、`agentkit/mcp/mcp_manager.py`、`agentkit/mcp/tool_call.py` 等关键模块。
- 项目整体已经是 gateway-first、memory-aware、tool-aware 的架构方向。

### 2.2 Promethea 当前主要不足

- `gateway` 仍更像“组织良好的服务集合”，尚未完全升级为统一控制平面。
- 工具调用仍明显带有“Prompt + 文本解析 JSON”的过渡特征，不够稳健。
- Prompt 组装尚未完全产品化，容易演化为分散拼接。
- Reasoning 仍偏内部机制，未形成完整产品能力与恢复模型。
- Memory 虽有清晰理念，但尚未完全成为可治理、可审计、可编辑的产品资产。
- Workspace、Skill、Workflow、Inspector、Doctor/Audit 等能力尚未完整成型。
- 缺少一套适合 Codex 长期接力的工程文档与任务拆分机制。

### 2.3 OpenClaw 的参考价值

OpenClaw 已经证明以下方向在真实产品中成立：

- Gateway 需要成为真正的控制平面。
- 工具与技能必须结构化管理，而不是仅靠 Prompt 提示。
- Runtime 一旦进入多工具、多轮对话、多入口场景，就必须解决 token 膨胀、配置脆弱、spawn 可靠性、审计与恢复问题。
- Security / Audit / Doctor 必须产品化。

### 2.4 差异化定位

Promethea 不应复制 OpenClaw，而应形成以下分工：

- **通用层**：追平 OpenClaw 的控制面、审计、工具治理、入口框架。
- **核心层**：做成比 OpenClaw 更强的多用户安全边界、长期记忆系统、推理控制与可恢复工作流。

---

## 3. 长期架构蓝图

Promethea 长期应收敛为 8 层架构。

### 3.1 Interface Layer

负责所有用户入口：

- Web UI
- HTTP API
- Desktop / Tauri
- 后续 IM 渠道
- 后续 Voice / Live 模式

原则：

- 接入层只做接入，不承载核心业务决策。
- 所有入口统一进入 Gateway Control Plane。
- 所有入口共享统一身份与权限模型。

### 3.2 Gateway Control Plane

负责统一编排：

- Session 生命周期
- Routing
- Agent Invocation
- Memory Orchestration
- Tool Arbitration
- Reasoning Policy Enforcement
- Audit Logging
- Health / Diagnostics

目标：

- Gateway 不只是后端入口，而是真正的控制平面。

### 3.3 Runtime Layer

负责一次运行的核心执行链路：

- 输入标准化
- 模式识别
- Prompt Assembly
- Memory Recall
- Planning / Reasoning
- Tool Execution
- Verification
- Response Synthesis

### 3.4 Memory Layer

负责所有记忆与画像能力：

- Working Memory
- Episodic Memory
- Semantic Memory
- Profile Memory
- Reasoning Template Memory

### 3.5 Tool & Skill Layer

负责能力组织：

- Primitive Tools
- MCP Tools
- Composed Skills
- Tool Policies
- Tool Health / Registry

### 3.6 Workspace Layer

负责 agent 的受控工作区：

- 文档
- 草稿
- JSON 配置
- 计划与证据文件
- 产物与快照

### 3.7 Workflow Layer

负责长任务与可恢复执行：

- 可暂停
- 可恢复
- 可人工介入
- 可 checkpoint
- 可回滚

### 3.8 Security / Observability Layer

负责：

- user / session / memory / workspace namespace 隔离
- secrets 管理
- audit
- trace
- doctor
- config validation / migration

---

## 4. 核心设计原则

### 4.1 Gateway-first

所有能力最终都要被 Gateway 收拢，不允许形成多个平行 runtime。

### 4.2 User-boundary-first

所有配置、会话、记忆、工具权限、工作区都必须显式绑定 `user_id`。

### 4.3 Structure over Prompt

凡是能通过结构化协议解决的问题，不用 Prompt 约束代替。

### 4.4 Prompt Assembly Ownership

Prompt 不是散落逻辑，而是一个可追踪、可裁剪、可压缩的装配过程。

### 4.5 Memory is Governed, not just Stored

记忆的核心不是“存进去”，而是“为什么写入、为什么召回、能否纠错、能否编辑”。

### 4.6 Reasoning must be Productized

推理不是隐藏黑盒，而应有模式、预算、结果评估、恢复能力与可解释性。

### 4.7 Safe by Default

权限默认保守，side-effect 工具默认受限，工作区默认 sandbox。

### 4.8 Long-term Codex Maintainability

任何新增模块都必须能被任务化、文档化、接口化，确保 Codex 可持续接力。

---

## 5. 关键对象模型（必须统一）

### 5.1 SessionState

字段至少包括：

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

### 5.2 RunContext

贯穿一次完整运行：

- 当前 `SessionState`
- 用户身份与权限
- Agent Persona
- Prompt Block 状态
- Memory Recall 结果
- Tool Availability / Policy
- Reasoning 状态
- Token / Cost Budget
- Workspace Handle

### 5.3 GatewayRequest / GatewayResponse

所有入口统一封装为：

- 输入内容
- 元数据
- 身份信息
- 路由提示
- Trace 信息

### 5.4 GatewayEvent

必须统一事件体系，不允许自由拼事件名。

### 5.5 ToolSpec

每个工具必须定义：

- `name`
- `description`
- `input_schema`
- `output_schema`
- `capability_type`
- `side_effect_level`
- `permission_scope`
- `timeout_ms`
- `retry_policy`
- `idempotency_hint`

### 5.6 MemoryRecord

每条记忆至少包含：

- `user_id`
- `scope`
- `source_session`
- `source_turn`
- `memory_type`
- `importance`
- `confidence`
- `write_gate_reason`
- `expiry_policy`
- `conflict_set_id`

### 5.7 ReasoningNode

每个节点至少具备：

- `node_id`
- `parent_id`
- `goal`
- `status`
- `memory_budget`
- `tool_budget`
- `evidence`
- `result`
- `verification_state`
- `checkpoint`

---

## 6. 长期 Workstreams

### Workstream A：Gateway Control Plane 正式化

#### 目标

把现有 `gateway` 从服务编排层升级成真正的统一控制平面。

#### 主要任务

1. 定义统一 `SessionState` 与 `RunContext`
2. 重构 `gateway/protocol.py` 为统一协议契约
3. 统一 `server.py` 的职责：接入、建上下文、调用 pipeline、回流事件
4. 让 `conversation_service` / `memory_service` / `tool_service` 都吃统一上下文
5. 统一事件体系
6. 打通 trace_id

#### 预期效果

- 所有入口共用同一种运行时语义
- 后续新增渠道、技能、工作流无需重复发明上下文
- 为审计、恢复、Inspector 打基础

#### 验收标准

- 每次运行都有完整 `RunContext`
- 每个关键事件可追踪到 session / user / trace
- 同一条运行链路可以重放关键步骤

---

### Workstream B：Conversation Pipeline 显式化

#### 目标

将一次 agent 运行固定为清晰的多阶段流水线。

#### 固定阶段

1. Input Normalization
2. Mode Detection
3. Memory Recall
4. Planning / Reasoning
5. Tool Execution
6. Response Synthesis

#### 主要任务

1. 每一阶段返回统一结果对象
2. 阶段之间只通过结构化对象传递，不直接跨层读写状态
3. 为每一阶段打 trace
4. 允许 future compaction / budget control 介入

#### 预期效果

- 减少逻辑耦合
- 明确 token 成本位置
- 方便 Codex 进行局部改造
- 减少“哪里都能拼 prompt、哪里都能调工具”的混乱

#### 验收标准

- 六阶段均有独立接口与日志
- 每轮运行的阶段结果可在 Session Inspector 中查看
- 任何阶段失败都可定位责任模块

---

### Workstream C：Prompt Assembly 产品化

#### 目标

把 Prompt 组装从隐式字符串拼接升级为显式 block renderer。

#### Prompt Blocks

- `identity_block`
- `policy_block`
- `memory_block`
- `tools_block`
- `workspace_block`
- `reasoning_block`
- `response_format_block`

#### 每个 Block 必须具备

- `source`
- `enabled`
- `token_estimate`
- `priority`
- `can_compact`
- `debug_render`

#### 主要任务

1. 重构现有 prompt 构建逻辑为 block system
2. 增加 token budgeting
3. 增加 block compaction 策略
4. 为不同 mode 提供 block policy

#### 预期效果

- Prompt Assembly 可追踪、可调优、可压缩
- 有利于防止上下文爆炸与 Prompt 污染
- 为技能、工作流、记忆召回提供稳定接口

#### 验收标准

- 每次运行都可导出 block 组成情况
- 能统计各 block token 占用
- 可针对特定 mode 禁用或压缩部分 block

---

### Workstream D：Tool Runtime 结构化升级

#### 目标

从“模型吐 JSON + 文本解析”升级到 schema-first 的工具运行时。

#### 主要任务

1. 定义统一 `ToolSpec`
2. 建立 `ToolRegistry`
3. 建立 `ToolPolicy`
4. 实现 `ToolExecutor`
5. 实现 `ToolResultNormalizer`
6. 实现 `ToolResultCompactor`
7. 将旧文本解析模式退化为 fallback

#### 工具分类

- `read_only`
- `workspace_write`
- `external_write`
- `privileged_host_action`

#### 预期效果

- 工具调用更稳健
- side-effect 风险可控
- 更适合多工具、多 agent、长工作流
- 更适合 Inspector / Audit / Replay

#### 验收标准

- 所有核心工具都有结构化 schema
- 工具调用失败有统一错误模型
- tool result 可被压缩与规范化
- side-effect 工具默认经过策略检查

---

### Workstream E：MCP Integration 产品化

#### 目标

把现有 MCP manager 从桥接能力升级为统一能力源之一。

#### 主要任务

1. 为每个 MCP service 维护健康状态
2. 同步并缓存工具目录
3. 展示 service / tool 能力快照
4. 为每个用户建立可见性和权限映射
5. 将 MCP tool 纳入统一 ToolSpec / ToolPolicy 系统

#### 预期效果

- MCP 不再只是底层桥，而是可治理的能力来源
- 为 Tool Panel / Skill Panel 提供基础数据
- 便于多用户隔离和工具审计

#### 验收标准

- 可以查看每个 MCP service 的在线状态、工具数、最后同步时间、最近失败原因
- MCP 工具调用可被统一 trace 与 audit

---

### Workstream F：Memory 治理化与产品化

#### 目标

把 Memory 从内部机制升级为产品资产。

#### Memory 类型

- `working_memory`
- `episodic_memory`
- `semantic_memory`
- `profile_memory`
- `reasoning_template_memory`

#### 主要任务

1. 明确 write gate 规则
2. 明确 recall policy 与 recall reason
3. 建立冲突处理机制
4. 建立 profile / semantic / episodic 的可视化面板
5. 提供用户可编辑能力
6. 逐步实现 importance / decay / summarization / contradiction handling

#### 预期效果

- 记忆可解释
- 记忆可纠偏
- 记忆真正为长期协作服务
- 可支撑项目级上下文与用户画像

#### 验收标准

- 所有记忆写入都经过 gate 并记录理由
- 召回结果包含来源与召回理由
- 可视化看到最近写入、冲突项、可编辑项

---

### Workstream G：Reasoning Tree 产品化

#### 目标

把现有 reasoning 能力升级为真正的产品级执行与恢复能力。

#### 模式

- `fast`
- `deep`
- `workflow`

#### 节点状态

- `pending`
- `running`
- `waiting_tool`
- `waiting_human`
- `succeeded`
- `failed`
- `skipped`

#### 主要任务

1. 明确 mode 行为差异
2. 为 `ReasoningNode` 引入统一状态机
3. 实现 verifier
4. 决定哪些 reasoning outcome 可持久化到 template memory
5. 在 UI 展示 Plan / Evidence / Outcome

#### 预期效果

- 推理具备可解释性
- 推理具备恢复能力
- 为 workflow engine 提供天然底座

#### 验收标准

- reasoning node 可被检查、恢复、验证
- verifier 可明确判定目标是否完成、是否需要用户确认、是否允许写入长期模板记忆

---

### Workstream H：Workspace / Canvas 路线

#### 目标

建立 Promethea 自己的受控工作区，而非简单复刻 OpenClaw Canvas。

#### 设计原则

- 一个 user / agent / project 对应一个 workspace
- 所有 agent 写操作仅允许发生在 workspace sandbox 内
- 所有工作区文件变动都有 trace 与版本快照

#### 第一版支持对象

- Markdown 文档
- 文本草稿
- JSON 配置
- TODO 板
- Plan / Evidence / Output artifacts

#### 主要任务

1. 定义 workspace root 与 sandbox policy
2. 建立 document store
3. 建立 snapshot / versioning
4. 与 reasoning / workflow 输出对接
5. 为 workspace 对象建立 UI 面板

#### 预期效果

- agent 不再只会回复文本，而能稳定产生产物
- 更适合写作、项目管理、研究整理等长期任务
- 有利于后续桌面端与工作流集成

#### 验收标准

- 所有 agent 产物都能写入 workspace
- 所有写操作都带 trace
- sandbox policy 生效且可审计

---

### Workstream I：Workflow Engine 与恢复能力

#### 目标

实现可暂停、可恢复、可人工接管的 workflow 执行系统。

#### 主要任务

1. 定义 workflow definition
2. 定义 step state / checkpoint model
3. 建立 resume / retry / compensation 机制
4. 对接 reasoning node
5. 支持 human approval gate
6. 将 workflow artifact 写入 workspace

#### 第一批官方 workflow

- GitHub Repo 审计
- 文档写作
- 每日新闻追踪
- 会议纪要 -> action items -> follow-up
- 长任务研究报告

#### 预期效果

- 长任务不再依赖单次上下文窗口完成
- agent 可持续推进复杂任务
- 更适合 Codex 与人工协同

#### 验收标准

- workflow 可在中断后恢复
- checkpoint 可回放关键状态
- 失败可重试或回滚

---

### Workstream J：Channels 与桌面体验框架

#### 目标

建立统一 channel adapter 框架，在不破坏核心 runtime 的情况下扩展入口。

#### 统一接口

- `ingest_message`
- `normalize_identity`
- `build_session_key`
- `emit_response`
- `emit_stream_chunk`
- `permission_check`

#### 第一批支持

- Web UI
- HTTP API
- Desktop / Tauri
- Telegram
- Slack 或飞书（二选一）

#### 主要任务

1. 定义 channel base interface
2. 重构现有 Web / HTTP 接入以复用该接口
3. 增加 Desktop resident mode
4. 完成一个 IM 渠道适配

#### 预期效果

- 入口扩展不再侵入核心 runtime
- 桌面端与消息端逐步具备统一体验

#### 验收标准

- 新增一个 channel 无需修改核心 pipeline 语义
- 各渠道 session 行为一致

---

### Workstream K：Security / Identity / Namespace 强化

#### 目标

把多用户隔离做成系统级特性，而不是项目约定。

#### 四层 namespace

- config namespace
- session namespace
- memory namespace
- workspace namespace

#### 主要任务

1. 统一 user / agent / session / workspace 标识体系
2. tool permission 按 user / agent 双层隔离
3. secret vault 独立化
4. side-effect tool 默认 deny
5. 审计所有跨 user 数据路径

#### 预期效果

- 多用户边界真正可验证
- 权限体系可审计
- 为后续多 agent / 多 workspace 提供安全基础

#### 验收标准

- 任意配置、记忆、产物都能追溯 user namespace
- 不同用户之间默认不可见、不可调用、不可互相污染

---

### Workstream L：Observability / Audit / Doctor

#### 目标

建立系统级可观测性与诊断能力，支撑长期迭代。

#### 必做 Trace 维度

- session trace
- memory trace
- tool trace
- reasoning trace
- model trace

#### 必做命令 / 页面

- `promethea doctor`
- `promethea audit`
- `promethea trace show <session_id>`
- `promethea memory inspect <user_id>`
- Session Inspector
- Memory Inspector
- Tool / MCP Health Inspector

#### 主要任务

1. 定义标准化事件与 trace schema
2. 建立链路追踪
3. 建立基础指标体系
4. 提供调试与审计页面
5. 对接 workspace / workflow / memory / tools

#### 预期效果

- 故障可定位
- 长任务可诊断
- Codex 能根据 trace 快速接手局部问题

#### 验收标准

- 一次运行可完整看到输入、召回、计划、工具、结果、写入
- doctor 能发现常见配置与运行问题

---

### Workstream M：Config / Schema / Migration 治理

#### 目标

避免配置系统成为长期脆点。

#### 原则

- 读路径 tolerant
- 写路径 strict
- schema 可迁移
- 支持 deprecation warning
- 支持 scoped query

#### 主要任务

1. 定义 config version
2. 提供 migration 机制
3. 提供 deprecation 提示
4. 避免返回超大 config blob 进入会话上下文
5. 区分运行时配置与用户偏好配置

#### 预期效果

- 配置演进可控
- 减少配置 typo 导致系统整体不可用的风险
- 减少 config 污染上下文

#### 验收标准

- 配置升级有 migration path
- 配置错误不会无提示地导致整系统不可用
- 配置查询支持 scope 化

---

### Workstream N：Skill Layer 与官方能力包

#### 目标

建立官方 curated skill 层，把工具与任务组织成长期可复用能力包。

#### Skill 结构

- `skill.yaml`
- `system_instruction.md`
- `tool_allowlist.yaml`
- `examples.json`
- `evaluation_cases.json`

#### 第一批官方 Skills

- GitHub Repo Analyst
- Project PM Assistant
- Research Writer
- News Tracker
- Memory Curator
- Coding Copilot
- Bank Materials Assistant

#### 主要任务

1. 定义 skill schema
2. 与 prompt blocks / tools / policies 对接
3. 建立 skill evaluator
4. 在 UI 暴露 skill 面板

#### 预期效果

- agent 能力可组合、可约束、可评估
- 便于后续 workflow 与 workspace 调用

#### 验收标准

- 每个 skill 都有明确工具白名单与评估样例
- skill 不依赖隐式 prompt 魔法运行

---

## 7. 文档与仓库治理（Codex 长期协作基础）

### 7.1 必须建立的文档目录

#### `docs/architecture/`

存放稳定结构说明：

- `runtime-overview.md`
- `gateway-protocol.md`
- `memory-model.md`
- `tool-runtime.md`
- `reasoning-model.md`
- `workspace-model.md`
- `workflow-model.md`

#### `docs/adr/`

每个关键架构决策一份 ADR，例如：

- ADR-001 RunContext
- ADR-002 Tool Schema
- ADR-003 Prompt Blocks
- ADR-004 Memory Write Gate
- ADR-005 Reasoning Modes
- ADR-006 Workspace Sandbox

#### `docs/backlog/`

每个任务一个文件，供工程师与 Codex 直接领取。

#### `docs/playbooks/`

存放操作指南：

- `how-to-add-a-tool.md`
- `how-to-add-a-channel.md`
- `how-to-add-a-skill.md`
- `how-to-change-memory-schema.md`
- `how-to-refactor-gateway-service.md`
- `how-to-debug-a-session.md`

### 7.2 Backlog Task 模板（强制）

每个任务文件必须包含：

- 背景
- 当前代码位置
- 目标
- 非目标
- 需要修改的模块
- 不允许修改的模块
- 接口变化
- 数据结构变化
- 测试要求
- 验收标准
- 回滚方案

### 7.3 PR 模板（强制）

每个 PR 必须回答：

1. 此改动属于哪个 Workstream
2. 是否改变 `user_id` 边界
3. 是否改变 Prompt token 结构
4. 是否改变 memory write path
5. 是否引入新的 side-effect tool 风险
6. 是否需要新增 ADR 或更新文档

### 7.4 Definition of Done

任意任务完成必须同时满足：

- 代码通过
- 单元测试通过
- 文档更新
- ADR 更新或说明不需要
- trace / audit 行为明确
- backward compatibility 说明清楚

---

## 8. 里程碑与优先级

### Phase 1：收紧内核（0–6 周）

#### 目标

把现有“好骨架”升级为可稳定运行的统一 runtime。

#### 范围

- Workstream A
- Workstream B
- Workstream C
- Workstream D（第一阶段）
- Workstream L（基础 trace）
- Workstream M（基础 config versioning）

#### 成果物

- `RunContext` / `SessionState`
- protocol schema
- event bus 统一
- 六阶段 pipeline
- prompt blocks
- tool metadata / schema
- trace_id 全链路

#### 成功标准

- 同一运行链路可完整回放
- 任何工具调用都能定位来源
- 新增入口不需要改核心状态结构

### Phase 2：能力产品化（6–12 周）

#### 目标

让核心能力变成可见、可调、可诊断的产品对象。

#### 范围

- Workstream E
- Workstream F
- Workstream G
- Workstream H
- Workstream K
- Workstream L
- Workstream N（第一批）

#### 成果物

- Memory Inspector
- Session Inspector
- Tool / Skill Panel
- MCP Health 面板
- Workspace Sandbox MVP
- `promethea doctor`
- `promethea audit`

#### 成功标准

- 日常可自用
- 新工程师可借 Inspector 理解故障
- Codex 可在不读全仓库的情况下完成局部任务

### Phase 3：差异化成型（12–24 周）

#### 目标

完成 Promethea 的长期护城河能力。

#### 范围

- Workstream I
- Workstream J
- Workstream F（高级治理）
- Workstream G（workflow mode）
- Workstream N（官方 skill pack）

#### 成果物

- Workflow Engine MVP
- Recoverable Node State
- Profile Editor
- Memory Conflict Review
- Per-user Multi-agent
- Official Curated Skills

#### 成功标准

- Promethea 不只是“能聊天和调工具”
- 而是“能长期记住、规划、恢复、交付”

---

## 9. 优先级矩阵

### P0（必须先做）

- Gateway control plane
- SessionState / RunContext
- Pipeline 显式化
- Prompt blocks
- Tool schema / policy
- 基础 trace / audit
- Namespace 与 user boundary

### P1（高优先级）

- Memory write gate / recall reason
- Reasoning mode / verifier
- MCP health / tool panel
- Workspace sandbox MVP
- Doctor / Inspector

### P2（中期增强）

- Workflow engine
- Desktop resident mode
- Telegram / Slack channel
- Skill layer
- Profile editor / conflict review

### P3（后续扩展）

- 多 agent per user
- voice / live mode
- 更丰富的 workflow pack
- 未来团队协作能力

---

## 10. Codex 长期协作方式

### 10.1 任务投喂原则

不要给 Codex 一次性“大而全任务”。只给三类任务：

- 小型纯重构
- 单一模块接口升级
- 单一 Inspector / Command / Policy 增补

### 10.2 每次交给 Codex 的最小输入包

每个任务至少给出：

- 相关 `docs/backlog/*.md`
- 相关 `docs/architecture/*.md`
- 涉及模块文件路径
- 当前接口说明
- 验收标准
- 不允许触碰的边界

### 10.3 Codex 输出要求

Codex 的改动必须同时提交：

- 代码
- 测试
- 文档更新
- 迁移说明（如有）
- 风险说明

### 10.4 不允许的 Codex 行为

- 无文档前提下跨多个核心模块大面积重构
- 修改 user boundary 逻辑但不更新 audit 与文档
- 通过 Prompt patch 替代结构化协议修复
- 在没有 schema / policy 的前提下新增 side-effect tool

---

## 11. 最终执行结论

Promethea 的正确路线不是成为“另一个 OpenClaw”，而是：

**在通用层追平 OpenClaw 已经验证有效的控制面、工具治理、审计与工作区框架；在核心层做出更强的多用户隔离、长期记忆、显式推理、可恢复工作流与 Prompt 主权。**

这份主计划的执行顺序应严格遵循：

1. 先收紧内核
2. 再产品化能力
3. 最后放大差异化

任何偏离这一顺序的扩展，都应被视为高风险变更。

---

## 12. 附：首批建议创建的 backlog 文件

建议立即创建以下任务文件，作为启动点：

1. `docs/backlog/001-runcontext-and-sessionstate.md`
2. `docs/backlog/002-gateway-protocol-unification.md`
3. `docs/backlog/003-conversation-pipeline-staging.md`
4. `docs/backlog/004-prompt-block-assembler.md`
5. `docs/backlog/005-tool-spec-and-policy.md`
6. `docs/backlog/006-trace-and-audit-foundation.md`
7. `docs/backlog/007-memory-write-gate.md`
8. `docs/backlog/008-reasoning-node-state-machine.md`
9. `docs/backlog/009-workspace-sandbox-mvp.md`
10. `docs/backlog/010-mcp-health-and-tool-panel.md`

这些任务完成后，Promethea 将具备长期可持续演进的基本工程条件。
