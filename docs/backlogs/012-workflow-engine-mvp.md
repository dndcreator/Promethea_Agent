# Backlog 012 - Workflow Engine MVP

## 1. 背景

Promethea 的长期目标之一是支持可暂停、可恢复、可人工介入的长任务执行。但如果没有明确的 Workflow Engine，系统会始终停留在“单轮会话 + 临时上下文”的模式，难以稳定支持：

- 长时间研究任务
- 文档写作与修订
- GitHub 仓库分析
- 每日追踪型任务
- 多步审批与人工确认
- 复杂多工具任务恢复

Promethea 已经有 Reasoning Tree、RunContext、Workspace、Memory 等基础方向，因此下一步应建立 Workflow Engine MVP。

---

## 2. 目标

本任务要完成：

1. 定义 Workflow 的基本模型
2. 定义 Step State / Checkpoint 结构
3. 支持暂停、恢复、重试
4. 支持与 Reasoning Node 对接
5. 支持产物写入 Workspace
6. 为 human approval gate 提供挂载点

---

## 3. 非目标

本任务不负责：

- 一次性实现完整 BPM/流程编排平台
- 一次性支持所有复杂 DAG 场景
- 一次性实现完整 UI 工作流编辑器
- 一次性支持团队协作审批流

本任务重点是建立 **可恢复 workflow 的最小骨架**。

---

## 4. 当前代码位置

优先检查：

- `gateway/reasoning_service.py`
- `gateway/conversation_service.py`
- `gateway/memory_service.py`
- `workspace` 相关模块（如已存在）
- 任何 task / job / long-running action 相关代码
- 任何 session 恢复 / checkpoint 相关代码

---

## 5. 目标设计

## 5.1 WorkflowDefinition

建议字段：

- `workflow_id`
- `workflow_type`
- `name`
- `description`
- `owner_user_id`
- `agent_id`
- `skill_id`
- `steps`
- `policy`
- `created_at`
- `updated_at`
- `status`

### 说明

第一版支持静态定义即可，不要求完整 DSL。

---

## 5.2 WorkflowRun

建议字段：

- `workflow_run_id`
- `workflow_id`
- `session_id`
- `user_id`
- `workspace_id`
- `status`
- `current_step_id`
- `checkpoint_id`
- `started_at`
- `updated_at`
- `completed_at`
- `run_metadata`

---

## 5.3 WorkflowStep

建议字段：

- `step_id`
- `step_type`
- `name`
- `description`
- `status`
- `inputs`
- `outputs`
- `requires_human_approval`
- `retry_policy`
- `timeout_policy`
- `depends_on`
- `artifact_targets`

### Step 类型建议第一版支持

- `reasoning_step`
- `tool_step`
- `memory_step`
- `artifact_step`
- `approval_step`
- `summary_step`

---

## 5.4 Checkpoint

建议字段：

- `checkpoint_id`
- `workflow_run_id`
- `step_id`
- `run_context_snapshot`
- `reasoning_state_snapshot`
- `memory_summary_snapshot`
- `workspace_artifact_refs`
- `created_at`

### 说明

Checkpoint 第一版不要求完整快照所有内容，但至少要支持恢复必要状态。

---

## 6. 推荐实现路径

## 6.1 第一步：定义 workflow schema

建议新增：

- `workflow/models.py`
- 或 `runtime/workflow_schema.py`

至少定义：

- `WorkflowDefinition`
- `WorkflowRun`
- `WorkflowStep`
- `Checkpoint`

---

## 6.2 第二步：定义 workflow engine 核心接口

建议新增：

- `workflow/engine.py`

核心方法建议：

- `start_workflow(...)`
- `resume_workflow(...)`
- `pause_workflow(...)`
- `retry_step(...)`
- `advance_to_next_step(...)`
- `create_checkpoint(...)`

---

## 6.3 第三步：先支持线性 workflow

第一版不要直接做复杂 DAG。  
先支持简单线性或近似线性步骤序列，确保：

- 可跑
- 可暂停
- 可恢复
- 可插入人工确认

---

## 6.4 第四步：对接 reasoning node

建议：

- workflow 中的 `reasoning_step` 直接复用 reasoning node/state machine
- 不重新发明一套完全不同的状态表达

---

## 6.5 第五步：对接 workspace

workflow 中的关键产物写入 workspace，例如：

- plan.md
- evidence.json
- draft.md
- final_summary.md

---

## 6.6 第六步：对接 memory

workflow 结束后，可：

- 写入 episodic summary
- 写入 project-related semantic memory
- 必要时更新 reasoning template memory

但仍必须走 Memory Write Gate。

---

## 7. 第一批官方 workflow 建议

建议第一版只支持少数高价值 workflow：

1. GitHub Repo 审计
2. 文档写作
3. 每日新闻追踪
4. 会议纪要 -> action items -> follow-up
5. 长任务研究报告

这些 workflow 都适合体现：

- reasoning
- memory
- tools
- workspace
- resume/checkpoint

---

## 8. 预期效果

完成后应达到：

- 长任务可跨单次上下文窗口继续推进
- agent 能形成“执行轨迹”而不是一次性输出
- 人工与 Codex 更容易协同处理中断任务
- Reasoning / Workspace / Memory 不再只是单轮助手能力，而开始进入持续执行系统

---

## 9. 测试要求

至少需要补以下测试：

1. `WorkflowDefinition` 创建测试
2. `WorkflowRun` 状态流转测试
3. 线性 workflow 主路径测试
4. checkpoint 创建测试
5. pause -> resume 测试
6. failed step -> retry 测试
7. approval step 卡住与恢复测试
8. artifact 写入 workspace 测试

---

## 10. 验收标准

本任务完成后，必须满足：

- 已存在统一 WorkflowDefinition / WorkflowRun / WorkflowStep / Checkpoint
- 已有 Workflow Engine 核心接口
- 至少一种线性 workflow 可运行
- workflow 可被暂停和恢复
- 至少一种 workflow 可写入 workspace artifact
- reasoning step 可复用 reasoning state / node 机制

---

## 11. 风险与注意事项

### 风险 1：一开始就做太复杂的流程编排
第一版必须控制范围，只做线性或近似线性流程。

### 风险 2：workflow 与 reasoning 分裂为两套系统
workflow step 尽可能复用 reasoning node 与 RunContext，不要各自发展一套状态结构。

### 风险 3：checkpoint 快照范围过大
第一版 checkpoint 只保留恢复所需关键状态，不要为了“完整”导致系统不可维护。

---

## 12. 回滚方案

如果接入影响过大，可以：

- 保留 workflow schema 与 engine 接口
- 仅支持一条官方 workflow
- 先以最小 checkpoint 范围运行
- 逐步接入更多 step 类型

不允许回滚到“没有 workflow 骨架”的状态。

---

## 13. 完成后应追加的文档更新

- `docs/architecture/workflow-model.md`
- `docs/architecture/runtime-overview.md`
- `docs/adr/ADR-012-workflow-engine-mvp.md`（建议新增）

---

## 14. 建议提交信息

- `feat(workflow): introduce workflow engine mvp`
- `feat(runtime): support resumable workflow runs and checkpoints`
