# Claude Code“意外开源”技术拆解与 Promethea 对比路线（2026-04）

## 1. 执行摘要（给工程师先看）

结论先行：你当前的架构方向和 Claude Code 的主轴是同向的，尤其是“显式执行循环 + 工具治理 + 可观察性 + 工作流化执行”。

真正的差距不在“有没有这些模块”，而在三件事：

1. `默认工作流的人机协作密度`（TODO/分解/子任务隔离是否成为默认行为）
2. `上下文预算治理强度`（是否把压缩、摘要、恢复点做成一等机制）
3. `生态面向对象`（插件/扩展/外部服务接入的标准化与发布路径）

你的项目已经具备可对齐底座（`RunContext`、分阶段 pipeline、ToolPolicy、workflow engine、trace/audit）。可借鉴路线不是“重做架构”，而是把这些能力提升成产品级默认路径。

## 2. 关于“意外开源”的事实边界（先校准认知）

社区讨论里的“Claude Code 意外开源”，本质上是两个阶段：

1. `社区逆向阶段`：基于发布产物（尤其 source map）进行源码复原与分析。
2. `官方公开阶段`：Anthropic 官方仓库与文档公开，能力边界更透明。

可验证证据：

- `leeyeel/claude-code-sourcemap` 明确描述了从 `claude code v0.2.8` 的 source maps 中提取并反混淆源码的过程与产物。
- `shareAI-lab/analysis_claude_code`/`learn-claude-code` 提供了系统化逆向分析与文档化拆解。
- `anthropics/claude-code` 官方仓库已公开，并在 README 中给出安装、插件与 SDK 路径（且标注 npm 安装已废弃）。

因此，工程上更稳妥的表述是：

- 早期存在“可被逆向还原的透明窗口”；
- 后续演进为官方更高透明度的公开工程化路线。

## 3. Claude Code 的工程主线（基于公开材料归纳）

## 3.1 Agent Loop 是第一性结构

在官方文档与社区拆解里，核心都指向“循环式执行”：

- 读取上下文
- 规划下一步
- 调用工具
- 消化观测结果
- 继续循环/收敛输出

这和你 `runtime-overview` 里“decision -> action -> observation -> next decision”的闭环高度一致。

## 3.2 上下文不是缓存，而是可治理预算

公开文档强调了 context management 与 `compact` 等机制，社区文档进一步展开为：

- 阶段性摘要
- 历史折叠
- 关键状态保留

这本质是把“长任务可持续性”从提示词技巧升级为运行时机制。

## 3.3 默认任务化协作（TODO / 子任务 / 隔离执行）

社区分析（尤其 learn-claude-code 的 task 文档）反复出现三类能力：

- TODO 作为中间状态管理
- 子任务化执行（subagent/task lanes）
- 工作区隔离（worktree/task isolation）

它们共同解决两个问题：

- 长任务中上下文漂移
- 并行修改时的冲突与可回滚性

## 3.4 权限与安全边界是产品默认，而非附加功能

官方文档把 permission modes、hooks、MCP 等作为一等能力暴露。这意味着：

- 工具调用不是“能调就调”，而是策略先行
- 审计、可见性、可控性是默认路径

## 3.5 生态扩展走向插件化与 SDK 化

官方 README 展示了 plugins 与 SDK 入口，核心信号是：

- 将“内部能力”变“可扩展平台能力”
- 通过稳定接口形成外部贡献与集成飞轮

## 4. 与 Promethea 的逐层对比（实事求是）

## 4.1 你已经明显对齐的层

1. `执行闭环`：你有明确 staged pipeline + reasoning loop。
2. `上下文对象化`：`SessionState` + `RunContext` 建模清楚。
3. `工具治理`：`ToolSpec/Registry/Policy` 已具备平台雏形。
4. `工作流桥接`：tool 执行与 workflow bridge 已打通。
5. `可观察性`：trace/audit 与 ops discovery endpoint 已存在。

判断：这些不是“demo 组件”，是可演进的骨架。

## 4.2 关键差距（也是最该投入的地方）

1. `任务中间态产品化不够`
你有 reasoning，但 TODO/子任务/恢复点还没有形成默认 UX 与统一协议。

2. `上下文治理策略还偏隐式`
有 recall/write gate，但“何时 compact、如何保真、如何回放”需要标准化。

3. `隔离并行执行能力需要抬到前台`
workflow 有 pause/resume，但“并行 task lane + 文件隔离 + 合并策略”可进一步产品化。

4. `生态对外接口尚未形成明确开发者飞轮`
你有 extension/plugin 基础，但文档、版本契约、发布路径还需更硬。

## 5. 可直接排期的借鉴路线（30/60/90 天）

## 5.1 30 天：把“可见的任务状态机”做成默认

目标：把复杂任务从“黑盒思考”变成“可追踪执行”。

落地项：

1. 定义统一 `TaskGraph` 协议（任务、子任务、依赖、状态、恢复点）。
2. 在 `planning_reasoning` 阶段强制产出结构化计划对象（而不只是文本计划）。
3. 将 TODO 面板接入 UI/API，支持外部读取当前执行图。
4. 每个工具调用绑定任务节点 ID，形成端到端 trace。

验收指标：

- 复杂请求（>3 次工具调用）中，90% 运行都有可读任务图。
- 工程师能从日志直接定位“哪一步计划导致失败”。

## 5.2 60 天：建立上下文预算控制面

目标：让长会话稳定性可预测。

落地项：

1. 引入 `ContextBudgetPolicy`：阈值、压缩触发、保留白名单。
2. 定义三层记忆摘要协议：`turn` / `task` / `session`。
3. 引入“压缩后回归校验”：关键约束（用户目标、禁用项、已完成事项）不能丢。
4. 提供 `/api/ops/context` 观测面：当前预算、压缩次数、摘要质量分。

验收指标：

- 长任务（>20 轮）成功率明显高于当前基线。
- 压缩后关键约束丢失率可量化并持续下降。

## 5.3 90 天：并行执行与生态化接口

目标：从“单代理执行器”升级为“任务编排平台”。

落地项：

1. 推出 `Task Lane`（隔离工作目录/权限/预算）。
2. 支持 lane 级审批策略（高风险工具默认人工确认）。
3. 固化插件契约版本（manifest + capability schema + compatibility matrix）。
4. 发布“官方扩展样板 + 自检脚本 + 发布流程文档”。

验收指标：

- 并行任务冲突率与回滚成本显著下降。
- 第三方可在不读核心源码情况下完成合规扩展接入。

## 6. 针对你当前项目的具体改造建议（代码位点）

1. 在 `gateway/conversation_pipeline.py` 增加 `task_graph_sync` 阶段（或并入 `planning_reasoning` 输出协议），统一承接 TODO/子任务状态。
2. 在 `gateway/reasoning_service.py` 中把“计划结构体”设为强类型输出，避免仅文本计划。
3. 在 `gateway/workflow_engine.py` 增加 lane 概念（`lane_id`、`workspace_scope`、`budget_scope`）。
4. 在 `gateway/http/routes/status.py` 和 ops surfaces 增加 context budget + task graph 观测字段。
5. 在 `docs/reference/config-contract.md` 增补策略开关：`context_budget`, `task_lane`, `lane_policy`。

## 7. 风险与误区（提前规避）

1. 不要把“子代理”当作多开线程；关键是协议化任务边界和可回放状态。
2. 不要只做摘要长度压缩；必须做约束保持与行为一致性校验。
3. 不要先做重 UI；先让 API 与 trace 可消费，再做前端视图。
4. 不要把插件当脚本市场；先把权限模型和兼容策略做硬。

## 8. 结语

你的判断是成立的：成熟度暂时不可能等同，但路线是对的，而且你现在的底座和 Claude Code 公开能力方向高度同向。

下一步最有杠杆的动作，不是继续堆 feature，而是把“任务化、预算化、隔离化、平台化”四件事做成默认工程路径。

---

## 参考来源

1. Anthropic 官方 Claude Code 文档（overview/how it works/permission modes/hooks/MCP）
- https://code.claude.com/docs/en/overview
- https://code.claude.com/docs/en/how-claude-code-works
- https://code.claude.com/docs/en/permission-modes

2. Anthropic 官方仓库 README
- https://github.com/anthropics/claude-code/blob/main/README.md

3. 社区逆向与复原材料
- https://github.com/leeyeel/claude-code-sourcemap
- https://github.com/shareAI-lab/analysis_claude_code
- https://github.com/shareAI-lab/learn-claude-code



## 9. 2026-03-31“今日泄露”补充核验（置信度分级）

为响应“今天是否有新泄露”的问题，这里单列时间敏感信息，并区分证据等级。

### A. 高置信（可独立复验）

1. `source map 可提取源码`这条技术路径本身是可复验的，并非今天才出现；社区仓库长期存在相关复原样本。
2. 官方 `anthropics/claude-code` 仓库与官方文档是公开可访问的。

### B. 中低置信（今日舆情，需谨慎引用）

1. 2026-03-31 当天出现多篇二手/三手文章与社区帖，宣称“再次因 .map 暴露完整源码”。
2. 这些来源普遍不是 Anthropic 官方安全公告或 GitHub 官方披露，细节存在互相转述与夸张风险。

### 对工程沟通的建议口径

- 不建议把“今天再次完整泄露”当作既定事实写进正式技术结论。
- 建议使用更稳妥表达：
  - `已确认存在过 source map 复原路径并被社区长期研究；`
  - `2026-03-31 出现新一轮泄露报道与讨论，但截至本文写作时未见同等级官方事件通告可完全佐证全部细节。`

### 今日核验参考（用于追踪，不等同官方定论）

- Reddit 讨论帖（2026-03-31）：
  - https://www.reddit.com/r/SaasDevelopers/comments/1s8pu4c/anthropic_just_leaked_claude_codes_entire_source/
- 当日二手分析文章（2026-03-31）：
  - https://thehuman2ai.com/blog/claude-code-source-leak
  - https://opentools.ai/news/anthropics-claude-code-cli-source-leak-stirs-ai-security-waves


## 10. 源码证据版（替代“猜测式拆解”）

本节只保留“能在源码或归档快照中直接定位”的事实。

### 10.1 今日泄露相关可验证源码面（结构级）

来自 `instructkr/claw-code` 的 `archive_surface_snapshot.json`（2026-03-31 相关镜像）可直接读到：

- 归档根目录：`archive/claude_code_ts_snapshot/src`
- 根级核心文件：`query.ts`、`tools.ts`、`commands.ts`、`Task.ts`、`QueryEngine.ts` 等
- 根级目录包含：`commands/`、`tools/`、`plugins/`、`remote/`、`server/`、`voice/`、`skills/`、`migrations/` 等
- 规模指标：`total_ts_like_files=1902`、`command_entry_count=207`、`tool_entry_count=184`

这说明“不是单一 CLI 脚本”，而是成熟的多子系统工程形态。

### 10.2 可读源码证据（提取源码仓库）

在 `leeyeel/claude-code-sourcemap` 可直接定位到关键执行路径（非二手总结）：

1. `src/query.ts`
- 存在会话执行主循环和预算控制参数（如 `maxTurns`、自动 compact 触发相关逻辑）。
- 存在权限跳过开关检查（如 `--dangerously-skip-permissions` 相关分支）。

2. `src/tools.ts`
- 工具注册不是“硬编码单工具”，而是分组装配：文件类、bash、web、notebook、task/todo、MCP 资源读取等。
- 存在 `getMCPTools`/权限过滤路径，说明 MCP 与权限门控在工具层就已整合。

3. `src/permissions.ts`
- 可见权限模式与“跳过权限”确认路径（例如 `bypassPermissionsModeAccepted` 等）。
- 可见 allowlist/规则解析逻辑（如 `parseAllowedTools`）。

4. `src/commands.ts`
- 命令分派中可见 `compact`、`permissions`、`mcp`、`doctor`、`memory`、`review` 等命令入口。
- 这和“上下文压缩 + 权限治理 + 诊断/评审”的产品能力是一致的。

### 10.3 对 Promethea 的“源码级”对照结论

基于上面代码证据（而非外部猜测），你最该对齐的是：

1. `执行循环产品化`：你已有 pipeline，但还需把任务图、恢复点和子任务状态做成默认协议输出。
2. `上下文预算机制`：不仅有 memory gate，还要有明确 compact 触发与回归校验。
3. `权限前置治理`：将 mode + tool allowlist 的联动策略下沉到调用前统一门禁。
4. `工具生态统一入口`：将本地工具、MCP、扩展工具在一个 registry/policy 面一致治理。

### 10.4 证据边界声明（避免误导工程团队）

- 我已将“今天舆情里的强断言”降级为待证信息。
- 本报告里的关键技术结论，均优先绑定到“可访问源码文件”或“归档快照索引”。
- 若你需要，我下一步可以把每条结论补成“文件路径 + 函数名 + 代码片段定位”的审计版附录（给工程师做逐条核查）。
