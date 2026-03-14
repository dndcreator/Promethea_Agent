# Backlog 011 - Memory Recall Policy 与 Memory Inspector

## 1. 背景

Promethea 的长期优势之一是分层记忆系统，但仅有写入治理还不够。真正决定记忆系统是否有价值的，不只是“存了什么”，而是：

- 本轮为什么召回这些记忆
- 这些记忆来自哪一层
- 它们和当前任务的关系是什么
- 是否存在无关召回、重复召回、过期召回
- 用户和工程师能否检查召回质量

如果没有明确的 Recall Policy 和可视化 Inspector，记忆系统会逐渐退化为：

- 难以调试的黑盒
- 到处注入 prompt 的隐式上下文池
- 质量不可控的“记忆拼盘”

本任务的目标是建立统一的 Memory Recall Policy，并提供第一版 Memory Inspector 基础能力。

---

## 2. 目标

本任务要完成：

1. 明确不同类型记忆的召回策略
2. 为召回结果附带 `recall_reason`、来源层、置信度、相关性说明
3. 限制无关、重复、过期记忆进入当前运行
4. 为 Prompt Assembly 提供更稳定、可解释的 memory block 输入
5. 建立第一版 Memory Inspector / Recall Inspector 所需的数据与查询基础

---

## 3. 非目标

本任务不负责：

- 一次性实现终极检索算法
- 一次性解决所有记忆排序问题
- 一次性完成完整 UI 平台
- 一次性实现知识图谱层面的复杂多跳检索

本任务重点是建立 **召回策略骨架 + 可解释结果 + 可检查能力**。

---

## 4. 当前代码位置

优先检查：

- `gateway/memory_service.py`
- 任何 memory retrieval / recall / query 相关模块
- Prompt 注入 memory 的位置
- `gateway/conversation_service.py`
- `gateway/reasoning_service.py`
- `gateway/tool_service.py`（如果工具执行依赖记忆）
- 任何 inspector/debug endpoint 相关模块

---

## 5. 目标设计

## 5.1 Memory Recall 的基本原则

记忆召回必须回答以下问题：

1. 为什么召回这条记忆？
2. 它来自哪一层记忆？
3. 它与当前任务的相关性是什么？
4. 它是长期画像、项目上下文、近期事件，还是推理模板？
5. 它是否仍然有效？
6. 是否有更高优先级的替代记忆？

---

## 5.2 建议 Recall 输入对象

建议定义：

### `MemoryRecallRequest`

至少包含：

- `request_id`
- `trace_id`
- `session_id`
- `user_id`
- `query_text`
- `normalized_query`
- `mode`
- `agent_id`
- `workspace_id`
- `active_skill_id`
- `active_workflow_id`
- `top_k`
- `allowed_memory_types`
- `filters`
- `debug_flags`

说明：

- 召回不应只依赖一段纯文本 query
- 必须结合 `RunContext` 中的结构化上下文

---

## 5.3 建议 Recall 输出对象

建议定义：

### `MemoryRecallResult`

至少包含：

- `memory_records`
- `summary`
- `recall_strategy`
- `applied_filters`
- `dropped_candidates`
- `metrics`

### `RecalledMemoryItem`

每条召回项建议包含：

- `memory_id`
- `memory_type`
- `source_layer`
- `content`
- `relevance_score`
- `confidence`
- `recall_reason`
- `source_session`
- `source_turn`
- `created_at`
- `last_used_at`
- `staleness_flag`
- `conflict_flag`

---

## 5.4 建议 Recall Policy 维度

召回应至少考虑以下维度：

### 维度 1：任务相关性
与当前 query、当前模式、当前 skill、当前 project 是否相关。

### 维度 2：层级优先级
例如：
- working memory
- episodic memory
- semantic memory
- profile memory
- reasoning template memory

不同模式下优先级可不同。

### 维度 3：新鲜度
过旧且无复用价值的记忆不应频繁进入 prompt。

### 维度 4：冲突与重复
重复项应合并或去重；冲突项应标记而非盲目同时注入。

### 维度 5：用户边界
严禁跨 user namespace 召回。

### 维度 6：模式差异
- `fast` 模式：尽量少量高置信召回
- `deep` 模式：允许更多结构化召回
- `workflow` 模式：优先与当前 workflow/project 强相关记忆

---

## 6. 建议 Recall 策略分层

### 6.1 Fast 模式

目标：

- 最小必要召回
- 避免 prompt 膨胀
- 优先高价值高置信度条目

建议：

- top_k 较小
- 优先 profile + 最近 episodic + 当前 working memory
- 默认排除低置信 reasoning template

### 6.2 Deep 模式

目标：

- 提供更丰富背景
- 支持显式规划与复杂工具调用

建议：

- 允许更多 semantic / episodic / project memory
- 允许 reasoning template 进入候选
- 但必须有排序与压缩机制

### 6.3 Workflow 模式

目标：

- 服务于特定长期任务
- 强调 project / workspace / checkpoint 相关上下文

建议：

- 优先当前 workflow/project 的 artifact 与 summary
- 优先当前 workspace 相关记忆
- 尽量避免无关个人偏好污染 workflow prompt

---

## 7. 推荐实现路径

## 7.1 第一步：建立 Recall Request / Result 模型

建议新增：

- `memory/recall_schema.py`
- 或 `gateway/memory_recall_schema.py`

要求：

- 可序列化
- 可落 trace
- 可被 Prompt Assembler 消费

---

## 7.2 第二步：在 memory_service 中实现统一 recall 入口

建议引入统一方法，例如：

- `recall_memory(request, run_context)`

要求：

- 所有主路径优先通过该入口召回
- 不再散落式在各模块中直接拼接 query 读记忆

---

## 7.3 第三步：实现 recall reason

至少对每条记忆给出简短理由，例如：

- `recent_session_context`
- `user_profile_match`
- `project_memory_match`
- `reasoning_template_match`
- `active_workflow_context`

第一版可规则生成，不要求复杂模型解释。

---

## 7.4 第四步：实现 dropped candidates 与过滤日志

这是后续 Inspector 的关键基础。

要求记录：

- 哪些候选被过滤掉
- 为什么被过滤
- 是因为重复、低相关、过期、冲突、越界，还是预算限制

---

## 7.5 第五步：建立 Memory Inspector / Recall Inspector 的查询基础

第一版不要求完整 UI，但至少应有：

- 列出某次 run 的 recall 结果
- 查看某条 recall item 的来源
- 查看被丢弃的候选及原因
- 查看 recall strategy 和 filters

可先通过：
- CLI
- debug endpoint
- JSON dump
实现。

---

## 8. 预期效果

完成后应达到：

- 记忆召回不再是黑盒
- Prompt 中的 memory block 更可解释
- 记忆系统更适合长期调优
- 工程师和 Codex 能定位“为什么这条记忆会被召回”
- 用户后续也可以在产品层面逐步拥有“看见和纠正记忆”的能力

---

## 9. 测试要求

至少需要补以下测试：

1. `MemoryRecallRequest` 创建测试
2. `MemoryRecallResult` 序列化测试
3. fast 模式 top_k 受限测试
4. deep 模式召回更多层测试
5. workflow 模式优先项目相关记忆测试
6. recall reason 非空测试
7. dropped candidates 记录测试
8. 跨 user namespace 召回禁止测试
9. 冲突 / 重复候选过滤测试

---

## 10. 验收标准

本任务完成后，必须满足：

- 已存在统一 `MemoryRecallRequest`
- 已存在统一 `MemoryRecallResult`
- 每条召回项含 `recall_reason`
- 至少一条主路径通过统一 recall 入口获取记忆
- recall 结果包含来源层与相关性信息
- 可查看被过滤候选及原因
- recall 行为已能被 trace / inspector 消费

---

## 11. 风险与注意事项

### 风险 1：召回结果信息过多，反而污染 prompt
Recall Result 与 Prompt 注入是两个阶段。Recall 可以保留丰富元信息，但注入 prompt 时仍应经过 Prompt Assembler 再裁剪。

### 风险 2：recall reason 过于敷衍
第一版 reason 可以简单，但必须真实反映实际选择路径，不能写空泛标签。

### 风险 3：把 recall policy 做成大而全复杂系统
第一版先用可解释规则体系，不急于做复杂学习排序。

---

## 12. 回滚方案

如果改造影响过大，可以：

- 保留 Recall Request / Result 模型
- 保留统一 recall 入口
- 先只在一条主路径启用 recall reason 与 dropped candidates 记录
- 其他路径继续兼容旧逻辑

不允许回滚到完全无统一 recall policy 的状态。

---

## 13. 完成后应追加的文档更新

- `docs/architecture/memory-model.md`
- `docs/architecture/memory-recall-policy.md`（建议新增）
- `docs/adr/ADR-011-memory-recall-policy.md`（建议新增）

---

## 14. 建议提交信息

- `feat(memory): introduce recall policy and recall inspector foundation`
- `refactor(memory): standardize recall request result and reasons`
