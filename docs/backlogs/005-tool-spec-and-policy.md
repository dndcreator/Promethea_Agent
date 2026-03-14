# Backlog 005 - Tool Spec 与 Tool Policy 统一化

## 1. 背景

Promethea 当前已经具备工具调用能力，并且已有 MCP manager 与工具相关模块。但现阶段工具调用仍带有明显的“模型输出 JSON + 解析”的过渡特征，工具的权限、风险、输入输出结构、side effect 等治理能力还未完全显式化。

随着系统进入：

- 多工具调用
- 多用户隔离
- reasoning mode
- workspace 写入
- workflow 长任务
- official skills

如果没有统一的 ToolSpec 与 ToolPolicy，工具系统会逐步失去可控性。

本任务的目标是建立统一的工具规范与策略系统。

---

## 2. 目标

本任务要完成：

1. 定义统一的 `ToolSpec`
2. 定义统一的 `ToolPolicy`
3. 建立 ToolRegistry
4. 区分不同风险级别的工具
5. 为 ToolExecutor、Audit、Inspector、Skill Allowlist 提供结构基础

---

## 3. 非目标

本任务不负责：

- 一次性重写所有工具实现
- 一次性淘汰所有旧工具调用路径
- 完整实现所有 side-effect 风险拦截器
- 完整实现 UI 面板

本任务重点是建立 **工具治理的统一数据结构与策略骨架**。

---

## 4. 当前代码位置

优先检查：

- `gateway/tool_service.py`
- `agentkit/mcp/mcp_manager.py`
- `agentkit/mcp/tool_call.py`
- 本地工具注册位置
- 任何 service / extension 中直接发起工具调用的代码

---

## 5. 目标设计

### 5.1 ToolSpec

每个工具必须定义：

- `tool_name`
- `description`
- `input_schema`
- `output_schema`
- `capability_type`
- `side_effect_level`
- `permission_scope`
- `timeout_ms`
- `retry_policy`
- `idempotency_hint`
- `source`（local / mcp / extension）
- `enabled`

### 5.2 工具分类

至少区分：

- `read_only`
- `workspace_write`
- `external_write`
- `privileged_host_action`

### 5.3 ToolPolicy

至少包含：

- user 级策略
- agent 级策略
- skill allowlist
- denylist
- mode-specific restrictions
- side-effect approval policy

---

## 6. 推荐实现路径

### 6.1 第一步：建立 ToolSpec 模型

建议新增：

- `tools/spec.py`
- 或 `gateway/tools/spec.py`

### 6.2 第二步：建立 ToolRegistry

Registry 负责：

- 注册本地工具
- 注册 MCP 工具映射
- 列出当前可用工具
- 根据 policy 过滤工具
- 按名称解析工具

### 6.3 第三步：建立 ToolPolicy 模型

建议支持：

- `is_allowed(tool_name, run_context)`
- `get_visible_tools(run_context)`
- `requires_confirmation(tool_name, run_context)`

### 6.4 第四步：逐步接入 tool_service

要求：

- 新工具优先注册为 ToolSpec
- tool_service 统一使用 registry + policy
- 旧工具路径可先通过 adapter 兼容

---

## 7. 预期效果

完成后应达到：

- 工具定义有统一形态
- 工具权限可控
- 不同工具的风险等级清晰
- MCP 工具与本地工具可统一看待
- 为后续 Skill、Workflow、Inspector、Audit 打基础

---

## 8. 测试要求

至少需要补以下测试：

1. ToolSpec 创建测试
2. ToolRegistry 注册与查询测试
3. ToolPolicy allow / deny 测试
4. side-effect 工具策略测试
5. MCP 工具映射进入 registry 测试

---

## 9. 验收标准

本任务完成后，必须满足：

- 已存在统一 ToolSpec
- 已存在统一 ToolPolicy
- 已存在 ToolRegistry
- 至少一条核心工具调用路径通过 registry + policy
- side-effect 工具默认不是裸奔可调用
- 新工具不允许继续只靠 prompt 文本描述接入

---

## 10. 风险与注意事项

### 风险 1：过度抽象工具规范
第一版重点是统一结构，不必追求特别复杂的策略系统。

### 风险 2：本地工具与 MCP 工具割裂
从一开始就要保证两者可进入同一 registry 视图。

### 风险 3：policy 只写文档不落代码
策略必须至少在一条主路径上真正生效。

---

## 11. 回滚方案

如改造影响过大，可：

- 保留 ToolSpec / ToolPolicy / Registry
- 先让部分核心工具走新路径
- 旧路径通过 adapter 兼容

不允许删除统一规范本身。

---

## 12. 完成后应追加的文档更新

- `docs/architecture/tool-runtime.md`（建议新增）
- `docs/adr/ADR-005-tool-spec-and-policy.md`（建议新增）

---

## 13. 建议提交信息

- `feat(tools): introduce ToolSpec ToolPolicy and registry`
- `refactor(tooling): standardize tool metadata and access policy`
