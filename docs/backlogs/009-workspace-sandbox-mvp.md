# Backlog 009 - Workspace Sandbox MVP

## 1. 背景

Promethea 后续要支持：

- 文档草稿
- 计划与证据产物
- workspace artifacts
- workflow 输出
- 更强的 agent 生产力能力

如果没有受控工作区，agent 的写操作会缺少边界与版本控制基础。

本任务负责建立 Workspace Sandbox 的第一版。

---

## 2. 目标

本任务要完成：

1. 定义 workspace 概念
2. 建立 sandbox policy
3. 建立最小 document/artifact 存储
4. 让 agent 产物可以落到 workspace 中
5. 为后续 canvas / desktop / workflow 打基础

---

## 3. 非目标

本任务不负责：

- 完整实现富文本编辑器
- 完整实现多人协同工作区
- 完整实现复杂版本控制系统

重点是建立 **受控工作区的 MVP**。

---

## 4. 建议设计

### 4.1 Workspace 粒度

建议第一版按以下逻辑管理：

- 一个 user 可有多个 workspace
- 一个 session / agent / project 可关联一个 workspace
- agent 只能在被授权的 workspace root 内读写

### 4.2 第一版对象类型

- Markdown 文档
- 纯文本草稿
- JSON 配置
- plan / evidence / output artifacts

---

## 5. 推荐实现路径

### 5.1 定义 WorkspaceHandle

建议包含：

- workspace_id
- user_id
- root_path
- permissions
- metadata

### 5.2 建立 sandbox policy

至少要确保：

- 不允许越过 workspace root
- 不允许任意宿主路径写入
- 所有写操作带 trace

### 5.3 建立 document store / artifact store

第一版可以轻量实现：

- create document
- update document
- list artifacts
- snapshot artifact

---

## 6. 预期效果

- agent 不再只会回文本
- 能稳定生成可管理产物
- 为 workflow / desktop / canvas 做准备

---

## 7. 测试要求

至少需要补以下测试：

1. workspace root 限制测试
2. 越界写入拒绝测试
3. artifact 创建测试
4. snapshot 创建测试
5. trace 信息挂载测试

---

## 8. 验收标准

- 已存在 WorkspaceHandle
- 已存在 sandbox policy
- 至少一类 artifact 可写入 workspace
- 越界写入默认不允许
- 写操作可被 trace / audit

---

## 9. 完成后应追加的文档更新

- `docs/architecture/workspace-model.md`
- `docs/adr/ADR-009-workspace-sandbox.md`

---

## 10. 建议提交信息

- `feat(workspace): introduce sandboxed workspace MVP`
- `feat(runtime): allow artifact generation into workspace`
