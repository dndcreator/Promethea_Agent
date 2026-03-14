# Backlog 016 - Namespace 边界与 Security Audit 基础

## 1. 背景

Promethea 与很多单用户个人助手项目的最大差异之一，是它从设计上强调：

- 多用户隔离
- user-scoped memory ownership
- 工具策略控制
- workspace 边界
- 更强的 runtime 边界治理

如果这些能力只是写在 README 里，而没有实际的 namespace 机制与 security audit 路径，那么系统在变复杂后很容易出现：

- 不同用户间配置混淆
- 记忆串用
- workspace 越界
- side-effect 工具越权
- trace 难以用于真正的安全检查

本任务负责建立 namespace 边界与安全审计基础。

---

## 2. 目标

本任务要完成：

1. 明确多层 namespace 模型
2. 审计关键路径上的 user boundary
3. 建立基础 security audit 机制
4. 为后续 doctor / audit / multi-agent per user 提供安全基础
5. 把“多用户隔离”从设计目标变成可检查行为

---

## 3. 非目标

本任务不负责：

- 一次性实现完整企业级权限系统
- 一次性实现复杂 RBAC / ABAC 平台
- 一次性解决所有未来安全问题

本任务重点是建立 **最基本且真实生效的 namespace 与 security audit 骨架**。

---

## 4. 当前代码位置

优先检查：

- `config_service`
- `memory_service`
- `tool_service`
- `workspace` 相关模块
- `gateway/server.py`
- 任何 user_id 注入、session 绑定、secret 读取相关逻辑
- observability / audit 相关模块

---

## 5. 目标设计

## 5.1 四层 namespace

建议至少明确以下四层：

1. `config namespace`
2. `session namespace`
3. `memory namespace`
4. `workspace namespace`

所有关键对象都必须能映射到其中一个或多个 namespace。

---

## 5.2 核心安全原则

### 原则 1：所有关键对象都显式绑定 user
至少包括：

- session
- memory record
- workspace
- tool policy
- skill visibility
- workflow run

### 原则 2：默认不跨 namespace
跨 user 访问必须默认禁止，而不是默认可见后再补规则。

### 原则 3：side-effect 工具默认保守
写宿主、写外部系统、调用高权限行为都必须有明确策略。

### 原则 4：secret 独立管理
用户敏感配置和密钥不应混在普通配置对象里任意传播。

---

## 5.3 Security Audit 范围（第一版）

至少覆盖：

- 跨 user memory access 尝试
- 跨 workspace 越界尝试
- side-effect tool 的权限检查
- secret 读取路径检查
- memory write decision 中的 namespace 信息
- workflow / skill / channel 中的 user boundary 检查

---

## 6. 推荐实现路径

## 6.1 第一步：梳理关键模型中的 namespace 字段

确保以下对象显式带有 user / namespace 信息：

- SessionState
- RunContext
- MemoryRecord
- ToolPolicy
- WorkspaceHandle
- WorkflowRun
- SkillVisibility / SkillContext（如适用）

---

## 6.2 第二步：为关键服务增加 boundary assertions

在以下 service 中至少增加基础断言或检查：

- memory_service
- tool_service
- workspace layer
- config access layer

检查内容包括：

- 当前 `user_id` 是否匹配
- namespace 是否越界
- 当前 agent 是否具备访问资格

---

## 6.3 第三步：建立 security audit 入口

建议新增：

- `security/audit.py`
- 或 observability 中的 security audit 子模块

至少支持：

- 收集安全相关 audit events
- 生成基础 audit report
- 被 `promethea audit` 使用

---

## 6.4 第四步：提供最小 audit 命令或 helper

第一版至少支持：

- 列出最近 namespace violation 尝试
- 列出最近 side-effect tool 执行
- 列出最近 workspace 越界阻止事件
- 列出最近 secret access 关键日志

---

## 7. 预期效果

完成后应达到：

- 多用户隔离开始可验证
- namespace 变成系统行为而不是约定
- 安全相关问题更容易被发现
- doctor / audit 能开始承担真正的边界检查功能
- 为 future multi-agent per user 和 team collaboration 打基础

---

## 8. 测试要求

至少需要补以下测试：

1. MemoryRecord user boundary 测试
2. WorkspaceHandle user boundary 测试
3. 跨 user memory access 拒绝测试
4. workspace 越界阻止测试
5. side-effect tool 权限检查 audit 测试
6. secret access 路径检查测试
7. security audit report 输出测试

---

## 9. 验收标准

本任务完成后，必须满足：

- 已明确四层 namespace
- 核心模型显式带 user / namespace 信息
- 至少 memory / workspace / tool 三类路径存在 boundary checks
- 已存在 security audit 记录入口
- 至少一条 audit 查询或报告路径可用
- 多用户隔离不再只是设计表述，而是已有真实检查点

---

## 10. 风险与注意事项

### 风险 1：为了“安全完整”做得过重
第一版重点是建立关键边界，不必一步到位做企业级权限系统。

### 风险 2：只有日志，没有真正的 boundary enforcement
必须至少让部分核心路径真正执行 boundary checks，而不是只记日志。

### 风险 3：secret 仍混在普通配置对象里
必须逐步分离 secret access 路径，至少在文档和代码入口上有边界。

---

## 11. 回滚方案

如影响过大，可以：

- 保留 namespace 模型与 security audit schema
- 先让最关键的 memory / workspace / tool 路径启用 boundary checks
- 其他模块渐进迁移

不允许回滚到完全没有 namespace / audit 机制的状态。

---

## 12. 完成后应追加的文档更新

- `docs/architecture/security-model.md`（建议新增）
- `docs/architecture/runtime-overview.md`
- `docs/adr/ADR-016-namespace-and-security-audit.md`（建议新增）

---

## 13. 建议提交信息

- `feat(security): introduce namespace boundary checks and security audit foundation`
- `refactor(runtime): make multi-user isolation auditable and enforceable`
