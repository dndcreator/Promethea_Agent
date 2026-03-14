# Backlog 008 - Reasoning Node State Machine

## 1. 背景

Promethea 已经有 reasoning 方向的骨架，但如果没有统一节点状态机，后续的：

- deep mode
- workflow mode
- verifier
- human approval
- recovery
- replay

都难以稳定落地。

本任务目标是把 reasoning node 从“内部结构”升级为“可恢复状态机”。

---

## 2. 目标

本任务要完成：

1. 定义 ReasoningNode 状态
2. 定义状态流转规则
3. 明确 node 与 tool / human / verifier 的关系
4. 为 workflow mode 提供天然底座

---

## 3. 非目标

本任务不负责：

- 完整实现 workflow engine
- 完整实现所有 planner 算法
- 一次性优化 reasoning 质量

重点是建立 **状态机骨架**。

---

## 4. 建议状态

- `pending`
- `running`
- `waiting_tool`
- `waiting_human`
- `succeeded`
- `failed`
- `skipped`

---

## 5. 推荐实现路径

### 5.1 定义 ReasoningNode 模型
建议包含：

- node_id
- parent_id
- goal
- status
- evidence
- result
- tool_calls
- human_gate
- verifier_state
- checkpoint

### 5.2 定义流转规则

例如：

- pending -> running
- running -> waiting_tool
- waiting_tool -> running
- running -> waiting_human
- waiting_human -> running
- running -> succeeded / failed / skipped

### 5.3 对接 reasoning_service

让 reasoning_service 至少在一条主路径使用状态机。

---

## 6. 预期效果

- reasoning 可恢复
- reasoning 可检查
- reasoning 与 workflow 更易对接
- verifier 更容易插入

---

## 7. 测试要求

至少需要补以下测试：

1. 初始状态测试
2. 状态流转合法性测试
3. waiting_tool -> running 恢复测试
4. waiting_human -> running 恢复测试
5. failed 状态终止测试

---

## 8. 验收标准

- 已存在统一 ReasoningNode 状态定义
- 已存在基本流转规则
- reasoning_service 至少一条路径接入状态机
- 节点状态可序列化与恢复

---

## 9. 完成后应追加的文档更新

- `docs/architecture/reasoning-model.md`
- `docs/adr/ADR-008-reasoning-node-state-machine.md`

---

## 10. 建议提交信息

- `feat(reasoning): introduce node state machine`
- `refactor(reasoning): make reasoning nodes stateful and recoverable`
