# Backlog 007 - Memory Write Gate

## 1. 背景

Promethea 的长期优势之一是分层记忆系统，但系统若没有统一的写入闸门，长期记忆很容易被以下内容污染：

- 临时上下文
- 推测性结论
- 幻觉结果
- 无法复用的细碎信息
- 与已有记忆冲突的写入

因此必须建立统一的 Memory Write Gate。

---

## 2. 目标

本任务要完成：

1. 建立记忆写入前判断机制
2. 区分不同类型内容的写入策略
3. 记录写入决策原因
4. 为 conflict handling、memory inspector、profile editor 提供基础

---

## 3. 非目标

本任务不负责：

- 一次性实现完整记忆冲突解决系统
- 一次性实现完整用户编辑界面
- 一次性实现复杂知识图谱合并规则

本任务重点是建立 **写入闸门**。

---

## 4. 当前代码位置

优先检查：

- `gateway/memory_service.py`
- 任何 memory write / extractor / summarizer 相关模块
- `gateway/reasoning_service.py`
- Response Synthesis 之后的持久化逻辑

---

## 5. 建议写入分类

至少区分：

- `working_memory`
- `episodic_memory`
- `semantic_memory`
- `profile_memory`
- `reasoning_template_memory`

---

## 6. 建议 Gate 判断维度

每次写入至少判断：

- 是否是事实还是推测
- 是否具有跨 session 价值
- 是否与当前项目/用户画像相关
- 是否属于短期上下文
- 是否与已有记忆冲突
- 是否需要用户确认
- 是否应延迟写入（先缓存在 working memory）

---

## 7. 推荐实现路径

### 7.1 定义 MemoryWriteRequest

建议包含：

- source text / source turn
- proposed memory type
- extracted content
- confidence
- related entities
- run / session metadata

### 7.2 定义 MemoryWriteDecision

建议包含：

- allowed / denied / defer
- target memory layer
- reason
- conflict candidates
- requires_user_confirmation

### 7.3 在 Response Synthesis 后接入 gate

所有长期写入必须经过 gate，而不是直接落库。

---

## 8. 预期效果

完成后应达到：

- 长期记忆不再裸写
- 记忆写入有理由可查
- 为用户画像、冲突处理、记忆可视化提供基础

---

## 9. 测试要求

至少需要补以下测试：

1. factual memory allow 测试
2. speculative memory deny 测试
3. short-lived context defer 测试
4. conflicting write 标记测试
5. decision reason 序列化测试

---

## 10. 验收标准

- 已存在 MemoryWriteRequest
- 已存在 MemoryWriteDecision
- 至少一条长期记忆写入路径经过 gate
- decision 含明确 reason
- speculative reasoning 不会直接写入长期层

---

## 11. 风险与注意事项

- 第一版不要求完美，只要求“先拦住乱写”
- deny / defer / allow 三态必须清晰
- gate 不应与底层数据库写逻辑强耦合

---

## 12. 完成后应追加的文档更新

- `docs/architecture/memory-model.md`
- `docs/adr/ADR-007-memory-write-gate.md`

---

## 13. 建议提交信息

- `feat(memory): introduce memory write gate`
- `refactor(memory): gate persistent writes with explicit decisions`
