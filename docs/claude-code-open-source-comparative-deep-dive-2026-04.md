# Claude Code 技术拆解与 Promethea 学习计划（更新版，2026-04-01）

## 1. 结论摘要

本报告基于三类输入合并而成：

1. 你给出的工程级机制拆解（runtime/context/permission/subagent/hook 等）。
2. 仓库现有文档与代码现状（Promethea）。
3. 2026-04-01 可检索到的最新公开信息（官方文档、官方仓库、社区逆向、主流媒体报道）。

核心结论：

- Claude Code 的工程核心仍然是 `可控执行 runtime`，不是 UI 产品壳。
- 你现在的 Promethea 架构方向是对齐的，但在 `任务中间态协议化`、`上下文编译器强度`、`子执行单元隔离`、`hook 中间件` 四块还不够“默认化”。
- 关于“3/31 泄露”事件：技术路径与舆情存在高可验证部分，但部分细节仍应按“非官方确认”处理，不能直接当成确定事实写入对外材料。

---

## 2. 事实边界与时间线（截至 2026-04-01）

### 2.1 高置信事实（官方或可复验）

1. Claude Code 官方文档持续更新，且 `2026-04-01` changelog 仍在发布新能力（例如权限与 hook 相关能力更新）。
2. Claude Code 官方代码仓库可公开访问（`anthropics/claude-code`）。
3. 社区存在基于 source map 的可复验逆向路径（`leeyeel/claude-code-sourcemap`）。

### 2.2 中置信事实（媒体报道，非官方安全公告）

1. 2026-03-31 出现“source map 导致源码暴露”的集中报道。
2. 多家媒体给出的版本和细节基本一致，但不等同于完整官方安全复盘。

### 2.3 工程建议口径

对内可以说：

- “source map 暴露路径曾被社区稳定复现，且 3/31 有新一轮报道。”

对外建议说：

- “截至 2026-04-01，已观察到相关公开报道与社区复现材料；详细影响范围以官方后续披露为准。”

---

## 3. Claude Code 机制拆解（修订版）

## 3.1 Runtime：单主循环 + 可派生执行单元

你的拆解“单线程 agent loop”方向成立。更准确表达：

- 主执行路径是串行 loop（决策 -> 行动 -> 观测 -> 下一步）。
- 复杂任务通过任务拆分/子执行单元扩展，不是传统多线程调度器。

工程意义：稳定性与可回放性优先于并发吞吐。

## 3.2 Context Engine：上下文编译器，而非简单拼接

“Context Compiler”这个判断非常准确。关键机制可抽象为：

- 多源输入聚合（会话、文件、工具结果、记忆、技能、运行状态）。
- 优先级裁剪和压缩（预算驱动）。
- 在长任务中通过 compact/summary 维持持续可执行性。

## 3.3 Tool Layer：统一执行边界 + 策略门控

Claude Code 的工具不是普通函数调用，而是 runtime 的外部能力边界：

- 调用前有策略检查。
- 调用后有结构化结果回流（而非原始 stdout 裸拼）。
- 高风险动作由 permission 模式和确认流程控制。

## 3.4 Permission：能力型安全（Capability-based）

核心不是角色表（RBAC），而是“当前运行实例可做什么”：

- 工具级授权。
- 模式化权限策略（严格、默认、绕过等）。
- 对子执行单元采用继承/快照语义，减少运行中权限漂移。

## 3.5 Subagent：隔离执行容器

可将 subagent 看成“受限 runtime 副本”：

- 独立上下文窗口。
- 独立预算/权限边界。
- 任务结束后通过结果而非全状态回灌主循环。

## 3.6 Hook：事件型中间件

你定义为 pipeline interceptor 是对的：

- 在关键事件位点注入（工具前后、权限前后、会话阶段）。
- 可用于策略扩展、审计和自动化协同。
- 本质上是“可编程运行时治理层”。

## 3.7 Settings：分层覆盖配置系统

配置并非单文件：

- 多层来源合并（组织/用户/项目/本地）。
- 作用面覆盖工具、权限、MCP、hooks、模型行为。
- 目标是可移植且可治理的 runtime 行为一致性。

## 3.8 Memory：轻量持久上下文（非全能长期记忆）

“文件记忆 + 注入 + 裁剪”的判断仍成立。它更像：

- 低成本长期偏好与约束保持机制。
- 不等于知识图谱型长期语义记忆系统。

---

## 4. Promethea 对照（基于当前仓库代码）

以下为当前代码可见事实（不是愿景）：

### 4.1 已对齐能力

1. 执行闭环与分阶段 pipeline  
   - `gateway/conversation_pipeline.py`
2. 上下文预算裁剪机制（prompt block compact）  
   - `gateway/prompt_assembler.py`
3. 统一工具抽象 + 本地/MCP 注册视图 + policy  
   - `gateway/tool_service.py`  
   - `gateway/tools/registry.py`  
   - `gateway/tools/policy.py`
4. workflow 运行引擎与协议面暴露  
   - `gateway/workflow_engine.py`  
   - `gateway/protocol.py`  
   - `gateway/http/routes/workflow.py`
5. CLI 作为协议入口（非 UI 依赖）  
   - `promethea_cli/main.py`

### 4.2 部分对齐（但未产品化为默认）

1. ReAct/ToT 与 workflow bridge 已存在，但任务图协议不统一。  
   - `gateway/reasoning_service.py`  
   - `gateway/conversation_pipeline.py`
2. 安全与策略存在两套实现痕迹（server 级与 tool service 级），需要统一权责边界。  
   - `gateway/server.py`  
   - `gateway/tools/policy.py`  
   - `gateway/tool_policy.py`

### 4.3 主要缺口

1. 没有 Claude Code 那种“可插拔 hook runtime”。
2. 没有成熟的“子执行单元协议”（spawn/隔离/合并）作为产品一等对象。
3. Context compiler 还偏实现细节，缺统一 `ContextBudgetPolicy` 合同与指标面板。
4. 任务中间态（plan/todo/checkpoint）缺统一 contract，跨 UI/CLI/API 语义还不够一致。

---

## 5. 学习计划（面向 Promethea，保留现有差异化）

## 5.1 Phase A（1-2 周）：把“执行语义”先协议化

目标：不改业务能力先改边界清晰度。

交付：

1. 新增 `TaskGraphContract`（任务节点、依赖、状态、证据、恢复点）。
2. 新增 `ContextBudgetContract`（预算阈值、触发原因、压缩策略、保留约束）。
3. 统一 tool policy 入口，明确 `gateway/server` 与 `ToolService` 的职责。
4. `/api/ops/protocol` 增加上述 contract 的版本字段。

验收：

- 任一复杂请求都可导出任务图 JSON。
- 策略拒绝路径只有一个 authoritative decision source。

## 5.2 Phase B（2-4 周）：补齐“中间件与隔离执行”

目标：把“可治理”做成 runtime 默认能力。

交付：

1. 新增 hook 总线（事件位点至少覆盖：pre_tool_call、post_tool_call、permission_decision、conversation_stage）。
2. 新增子执行单元协议（`spawn`, `run`, `collect`, `merge`），先单机实现，不做分布式。
3. 每个子执行单元附带 permission snapshot 与 budget snapshot。
4. 在 CLI 暴露调试命令：`ops hooks`, `ops tasks`, `ops budgets`。

验收：

- 子执行单元失败不会污染主任务上下文状态。
- hook 可以拦截并审计高风险工具动作。

## 5.3 Phase C（4-8 周）：工程化与生态化

目标：从“可运行”升级到“可集成平台”。

交付：

1. 扩展/插件 manifest 版本矩阵（兼容性声明 + 能力声明）。
2. 官方工具包分层（基础 I/O、网络、数据处理、workflow、memory）+ contract tests。
3. 场景化 E2E 测试（真实业务流程，不仅单元测试）。
4. 发布“协议优先接入指南”（UI 仅作为消费者之一）。

验收：

- TOC（本地助手）与 TOB（协议接入）能力面一致。
- 新接入方可在不读核心代码的前提下完成接入。

---

## 6. 这次“泄露事件”对 Promethea 的直接工程启发

1. 发布链路要默认做 sourcemap 风险审计（尤其 CLI/前端构建产物）。
2. 需要产物级安全检查清单（构建产物、打包文件、调试符号、密钥扫描）。
3. 将“可观察性”从功能日志提升为 `release-gate`（不通过不发布）。
4. 对外文档中的事实表述要有证据等级，避免把舆情当官方结论。

---

## 7. 对你给出的拆解的修订结论

你那份拆解总体方向正确，尤其以下四点可直接作为内部设计原则：

1. `Runtime first`：先定义执行语义，再做交互壳。
2. `Context compiler first`：上下文治理是第一工程问题。
3. `Capability security first`：权限必须在执行路径内，而非 UI 层。
4. `Protocol first`：CLI/API/UI 都应是同一协议的不同入口。

需要修正的一点是“绝对单线程”表述：应改为“单主循环 + 可隔离子执行单元”，更符合工程现实。

---

## 8. 参考来源（按可信度分层）

### A. 官方（高置信）

1. Claude Code 文档总览  
   - https://docs.claude.com/en/docs/claude-code/overview
2. Claude Code Permission Modes  
   - https://code.claude.com/docs/en/permission-modes
3. Claude Code Changelog（含 2026-04-01 更新）  
   - https://code.claude.com/docs/en/changelog
4. Anthropic 官方仓库 README  
   - https://github.com/anthropics/claude-code/blob/main/README.md

### B. 可复验社区技术材料（中高置信）

1. Source map 复原仓库  
   - https://github.com/leeyeel/claude-code-sourcemap
2. 逆向分析与学习仓库  
   - https://github.com/shareAI-lab/analysis_claude_code  
   - https://github.com/shareAI-lab/learn-claude-code

### C. 媒体报道（中置信，需与官方信息区分）

1. Business Insider 报道（2026-03-31）  
   - https://www.businessinsider.com/anthropic-leak-reveals-claude-code-internal-source-code-2026-3
2. Axios 报道（2026-03-31）  
   - https://www.axios.com/2026/03/31/anthropic-claude-code-leak
3. The Verge 报道（2026-03-31）  
   - https://www.theverge.com/news/648567/anthropic-claude-code-leak

