# Backlog 004 - Prompt Block Assembler

## 1. 背景

Promethea 当前已经具备 gateway-first、memory-aware、tool-aware 的架构方向，但 Prompt 组装仍可能散落在 conversation、tool、memory、reasoning 等模块中，形成隐式拼接。

随着系统逐步引入：

- 多用户上下文
- 分层记忆
- tool policy
- reasoning mode
- workspace / workflow
- skills

如果没有统一的 Prompt Assembly 机制，将很容易出现以下问题：

- prompt 来源不可追踪
- token 预算失控
- 新功能不断污染系统提示
- 同类上下文重复注入
- 不同 mode 下 prompt 行为不稳定

本任务的目标是建立 block-based prompt assembler，使 Prompt 从“字符串拼接”升级为“结构化装配”。

---

## 2. 目标

本任务要完成：

1. 定义 Prompt Block 的统一模型
2. 建立 Prompt Assembler
3. 把现有 prompt 组装逻辑收敛到 assembler
4. 为 token budgeting、block compaction、mode-specific policy 提供基础
5. 让 Prompt 组装过程可追踪、可调试、可裁剪

---

## 3. 非目标

本任务不负责：

- 一次性优化所有 prompt 内容质量
- 设计最终完美的 token 压缩策略
- 改写所有 agent persona 内容
- 全面解决所有 prompt engineering 问题

本任务重点是建立 **Prompt 装配机制**。

---

## 4. 当前代码位置

优先检查：

- `gateway/conversation_service.py`
- 任何 prompt builder / system prompt / memory injection 相关模块
- `gateway/reasoning_service.py`
- `gateway/tool_service.py`
- `gateway/memory_service.py`

如果已有 prompt 相关 helper，应统一纳入 assembler 的输入来源。

---

## 5. 目标设计

### 5.1 Prompt Block

建议每个 Prompt Block 至少包含：

- `block_id`
- `block_type`
- `source`
- `content`
- `enabled`
- `priority`
- `token_estimate`
- `can_compact`
- `metadata`

### 5.2 Block 类型

第一版至少支持：

- `identity_block`
- `policy_block`
- `memory_block`
- `tools_block`
- `workspace_block`
- `reasoning_block`
- `response_format_block`

### 5.3 Prompt Assembler

核心职责：

1. 接收 `RunContext`
2. 按当前 mode 和 policy 选择 block
3. 计算 block 顺序
4. 估算 token 成本
5. 在需要时压缩 / 丢弃低优先级 block
6. 输出最终 prompt 与调试信息

---

## 6. 推荐实现路径

### 6.1 第一步：定义 PromptBlock 模型

建议新增：

- `runtime/prompt_blocks.py`
- 或 `gateway/prompt_blocks.py`

要求：

- 结构清晰
- 可序列化
- 可调试输出
- 不依赖具体 LLM provider

### 6.2 第二步：定义 PromptAssembler

建议新增：

- `runtime/prompt_assembler.py`

核心方法建议：

- `collect_blocks(run_context)`
- `sort_blocks(blocks)`
- `estimate_tokens(blocks)`
- `compact_blocks(blocks, budget)`
- `render_prompt(blocks)`

### 6.3 第三步：接入 conversation pipeline

接入位置建议：

- Stage 4 之前或与 planning/reasoning 协同
- 最终在 Response Synthesis 之前得到模型输入所需 prompt

### 6.4 第四步：增加调试输出

至少支持：

- 当前使用了哪些 block
- 每个 block 来源
- 每个 block token 估算
- 哪些 block 被压缩或丢弃

---

## 7. 预期效果

完成后应达到：

- Prompt 不再是到处散落的字符串
- Prompt 构建路径可解释
- 便于做 token 控制
- 便于技能、工作流、记忆模块稳定接入
- 便于 Codex 局部修改 prompt 机制而不破坏全局

---

## 8. 测试要求

至少需要补以下测试：

1. PromptBlock 创建测试
2. PromptAssembler 收集 block 测试
3. block 排序测试
4. token 估算测试
5. compact 策略基础测试
6. assembler 输出调试信息测试

---

## 9. 验收标准

本任务完成后，必须满足：

- 已有统一 PromptBlock 模型
- 已有 PromptAssembler
- conversation 主路径至少一条使用 assembler
- 至少能输出 block 调试信息
- 不同 mode 下可启停部分 block
- 后续 prompt 新逻辑必须优先接入 block system

---

## 10. 风险与注意事项

### 风险 1：直接把旧 prompt 原样拆成 block，仍然不可维护
需要在拆分时顺便明确来源与职责。

### 风险 2：block 太多，反而更乱
第一版先控制 block 类型数量，不要过度细分。

### 风险 3：token 估算过度复杂
第一版只需近似估算即可，重点是机制先存在。

---

## 11. 回滚方案

如接入导致影响过大，可以：

- 保留 PromptBlock / PromptAssembler 模型
- 仅在一条主路径启用 assembler
- 其他路径暂时通过 adapter 调旧逻辑

不允许回滚到完全没有 block system 的状态。

---

## 12. 完成后应追加的文档更新

- `docs/architecture/runtime-overview.md`
- `docs/architecture/prompt-assembly.md`（建议新增）
- `docs/adr/ADR-004-prompt-blocks.md`（建议新增）

---

## 13. 建议提交信息

- `feat(prompt): introduce block-based prompt assembler`
- `refactor(runtime): move prompt assembly into structured blocks`
