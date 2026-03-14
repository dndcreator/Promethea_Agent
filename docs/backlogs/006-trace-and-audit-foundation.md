# Backlog 006 - Trace 与 Audit 基础设施

## 1. 背景

Promethea 后续要支持：

- 多阶段 pipeline
- 多工具调用
- 分层记忆
- reasoning tree
- workspace artifacts
- workflow 恢复
- 多用户隔离

这些能力如果没有统一 trace 与 audit，会导致：

- 无法定位问题
- 无法回放运行链路
- 无法审计跨用户边界风险
- 无法支撑 inspector
- 无法支撑 Codex 在复杂系统中持续接力

本任务负责建立最基础的 trace 与 audit 基础设施。

---

## 2. 目标

本任务要完成：

1. 定义统一 trace schema
2. 定义统一 audit event schema
3. 确保关键运行链路带有统一追踪字段
4. 为 Session Inspector / Tool Inspector / Memory Inspector 提供底层数据
5. 建立最基础的 doctor / audit 扩展点

---

## 3. 非目标

本任务不负责：

- 一次性实现完整可视化平台
- 一次性实现高级指标看板
- 一次性实现完整 SIEM/安全平台式审计系统

本任务重点是建立 **最小但可扩展的追踪与审计骨架**。

---

## 4. 当前代码位置

优先检查：

- `gateway/events.py`
- `gateway/server.py`
- `gateway/conversation_service.py`
- `gateway/memory_service.py`
- `gateway/tool_service.py`
- `gateway/reasoning_service.py`

以及任何统一 logger / telemetry 相关代码。

---

## 5. Trace 范围

第一版至少覆盖：

- session trace
- run trace
- memory trace
- tool trace
- reasoning trace
- response synthesis trace

---

## 6. Audit 范围

第一版至少覆盖：

- 跨用户边界访问尝试
- 工具权限检查结果
- side-effect 工具执行
- memory write decision
- workspace 写操作
- 配置异常 / 安全相关异常

---

## 7. 推荐实现路径

### 7.1 第一步：定义 TraceEvent / AuditEvent

建议新增统一 schema，例如：

- `observability/trace.py`
- `observability/audit.py`

### 7.2 第二步：打通统一追踪字段

关键字段必须至少包括：

- `trace_id`
- `request_id`
- `session_id`
- `user_id`
- `agent_id`
- `timestamp`
- `source_module`

### 7.3 第三步：在关键主路径插桩

优先插桩：

- gateway request received
- memory recall started / finished
- tool execution started / finished / failed
- reasoning started / finished
- response synthesized
- memory write decided

### 7.4 第四步：提供最小查询入口

第一版至少提供：

- trace dump / query helper
- audit log query helper

后续再扩展 inspector UI。

---

## 8. 预期效果

完成后应达到：

- 一次运行可被追踪
- 核心安全/权限动作可被审计
- 问题可定位到阶段和模块
- 为后续 Inspector 和 doctor 提供基础

---

## 9. 测试要求

至少需要补以下测试：

1. TraceEvent 创建与序列化测试
2. AuditEvent 创建与序列化测试
3. 主路径 trace 字段完整性测试
4. side-effect tool 的 audit 测试
5. memory write decision 的 audit 测试

---

## 10. 验收标准

本任务完成后，必须满足：

- 已存在统一 TraceEvent / AuditEvent 模型
- 一条主路径可完整看到 run trace
- 至少 tool / memory / reasoning 三类动作会写入 trace
- 至少 side-effect tool 与 memory write decision 会写入 audit

---

## 11. 风险与注意事项

### 风险 1：日志过多，影响可读性
第一版重点是关键事件，不要把所有低价值细节都打进去。

### 风险 2：trace 与 audit 混淆
trace 用于运行链路可视化；audit 用于权限、安全、重要决策。两者要分清。

### 风险 3：没有统一字段
必须统一 trace_id / session_id / user_id，否则后续 inspector 无法做。

---

## 12. 回滚方案

如影响过大，可先：

- 保留统一 schema
- 只在关键主路径插桩
- 其他模块后续渐进接入

---

## 13. 完成后应追加的文档更新

- `docs/architecture/observability.md`（建议新增）
- `docs/adr/ADR-006-trace-and-audit.md`（建议新增）

---

## 14. 建议提交信息

- `feat(observability): introduce trace and audit foundation`
- `refactor(runtime): add structured tracing and audit events`
