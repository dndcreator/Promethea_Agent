# Backlog 010 - MCP Health 与 Tool Panel 基础能力

## 1. 背景

Promethea 当前已有 MCP manager，但 MCP 目前更多是底层桥接能力，而不是可治理、可查看、可诊断的产品对象。

随着工具和技能增长，需要至少能回答：

- 当前有哪些 MCP service 在线
- 每个 service 暴露哪些工具
- 最近同步时间是什么
- 最近失败原因是什么
- 当前用户是否可见这些工具

本任务负责建立 MCP 健康状态与工具面板的第一版基础能力。

---

## 2. 目标

本任务要完成：

1. 为 MCP service 建立健康状态模型
2. 为 MCP tools 建立可查看目录
3. 将 MCP tools 纳入统一工具视图
4. 为后续 Tool Panel / Skill Panel 提供数据来源

---

## 3. 非目标

本任务不负责：

- 完整实现复杂 UI
- 完整实现所有 MCP 生命周期管理
- 一次性解决所有 MCP 错误恢复问题

本任务重点是建立 **可见性与健康信息基础**。

---

## 4. 当前代码位置

优先检查：

- `agentkit/mcp/mcp_manager.py`
- 工具注册相关模块
- 任何与 service discovery / tool listing 相关代码

---

## 5. 建议设计

### 5.1 MCPServiceHealth

建议字段：

- service_name
- status
- last_seen_at
- last_sync_at
- tool_count
- last_error
- source
- user_visibility

### 5.2 MCPToolDescriptor

建议字段：

- tool_name
- service_name
- description
- input_schema_summary
- status
- enabled
- last_updated_at

---

## 6. 推荐实现路径

### 6.1 第一步：在 mcp_manager 中维护 health snapshot

至少支持：

- online / offline / degraded
- last sync time
- last error

### 6.2 第二步：生成统一 tool listing

把 MCP 工具转成统一 descriptor。

### 6.3 第三步：暴露查询接口

至少提供：

- list services
- get service health
- list tools by service
- list visible tools for user

### 6.4 第四步：为后续 panel / inspector 预留接口

可以先是 CLI / JSON / debug endpoint，再逐步接 UI。

---

## 7. 预期效果

- MCP 不再是黑盒
- 工具来源更清晰
- 问题定位更容易
- 为 skill allowlist 与 tool policy 提供数据

---

## 8. 测试要求

至少需要补以下测试：

1. service health snapshot 测试
2. service online / offline 状态测试
3. tool listing 测试
4. last_error 持久化/输出测试
5. user visibility 过滤测试

---

## 9. 验收标准

- 已存在 MCPServiceHealth
- 已存在 MCPToolDescriptor
- 可查询服务健康状态
- 可查询工具目录
- MCP 工具至少在一条统一工具视图中可见

---

## 10. 完成后应追加的文档更新

- `docs/architecture/tool-runtime.md`
- `docs/adr/ADR-010-mcp-health-and-visibility.md`

---

## 11. 建议提交信息

- `feat(mcp): add service health snapshots and tool descriptors`
- `feat(tools): expose MCP health and tool panel foundation`
