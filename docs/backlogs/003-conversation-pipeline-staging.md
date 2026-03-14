# Backlog 003 - Conversation Pipeline 分阶段化

## 1. 背景

Promethea 当前已经有 conversation、memory、tool、reasoning 等核心模块，也已经具备 gateway-first 的总体结构。但一次完整对话运行的核心执行链路仍未完全显式化。

当前问题主要表现为：

- 单轮运行的不同步骤边界不够固定
- Prompt 组装、记忆召回、工具调用、推理决策可能交织在一起
- 新增功能时容易把逻辑继续堆进 conversation service
- 不利于 trace、inspector、workflow 恢复与 Codex 局部重构

因此需要把 Conversation Runtime 显式收敛成固定阶段的 Pipeline。

---

## 2. 目标

本任务要完成：

1. 定义单轮运行的固定阶段
2. 让每一阶段有明确输入输出
3. 让阶段之间通过结构化对象衔接
4. 为 Prompt Assembly、Memory Recall、Tool Runtime、Reasoning、Workflow 提供稳定挂载点
5. 降低 conversation service 的“上帝模块”风险

---

## 3. 非目标

本任务不负责：

- 完整实现所有阶段的最终版本
- 一次性重写所有 conversation 代码
- 完整实现 workflow engine
- 完整实现所有 mode 的最终策略
- 解决所有历史 prompt 设计问题

本任务重点是 **把 Pipeline 骨架显式建立起来**。

---

## 4. 当前代码位置

优先检查以下模块：

- `gateway/conversation_service.py`
- `gateway/server.py`
- `gateway/memory_service.py`
- `gateway/tool_service.py`
- `gateway/reasoning_service.py`

如果项目里还有 message manager、response builder、prompt builder 等模块，也应纳入梳理。

---

## 5. 目标 Pipeline

建议将单轮运行固定为以下 6 个阶段：

1. Input Normalization
2. Mode Detection
3. Memory Recall
4. Planning / Reasoning
5. Tool Execution
6. Response Synthesis

该顺序作为默认主路径；允许后续在具体 mode 下进行裁剪，但不能破坏总体语义。

---

## 6. 各阶段定义

## 6.1 Stage 1 - Input Normalization

### 职责

- 标准化原始输入
- 解析文本、附件、元数据
- 绑定 `session_id / user_id / trace_id`
- 初始化或更新 `RunContext`

### 输入

- `GatewayRequest`
- `RunContext`（可为空或半初始化）

### 输出

- `NormalizedInput`
- 初始化后的 `RunContext`

### 说明

该阶段不做复杂业务推理，不直接调用工具，不直接写记忆。

---

## 6.2 Stage 2 - Mode Detection

### 职责

判断本次运行应采用的模式，例如：

- `fast`
- `deep`
- `workflow`

### 判断依据

- 用户显式指令
- 当前 session 状态
- 工具需求
- 任务复杂度
- 风险与预算约束

### 输出

- `ModeDecision`

### 说明

Mode Detection 只负责“决定怎么跑”，不负责真正执行复杂推理。

---

## 6.3 Stage 3 - Memory Recall

### 职责

- 根据当前输入与上下文召回相关记忆
- 区分 working / episodic / semantic / profile / reasoning template memory
- 为召回结果附带 recall reason、来源、置信度

### 输出

- `MemoryRecallBundle`

### 说明

本阶段只负责“取回合适记忆”，不负责在这里进行大量写入。

---

## 6.4 Stage 4 - Planning / Reasoning

### 职责

- 判断是否需要显式规划
- 在需要时构建 reasoning tree 或 planner state
- 决定是否需要工具调用、是否需要进一步拆分步骤

### 输出

- `PlanResult`
- 或更新后的 `ReasoningState`

### 说明

并不是每轮都需要复杂 reasoning，但该阶段必须始终存在，以便统一模式切换。

---

## 6.5 Stage 5 - Tool Execution

### 职责

- 根据 Plan / Reasoning / Policy 执行允许的工具
- 规范化工具输入输出
- 写入 trace / audit
- 汇总工具执行结果

### 输出

- `ToolExecutionBundle`

### 说明

本阶段不负责最终写用户回复，而是提供可被后续合成阶段消费的结果。

---

## 6.6 Stage 6 - Response Synthesis

### 职责

- 综合输入、记忆、工具、推理结果
- 生成最终回复
- 生成需要的 artifacts
- 触发 memory write gate（如适用）
- 形成 `GatewayResponse`

### 输出

- `ResponseDraft`
- `GatewayResponse`

### 说明

本阶段是“合成与收口”阶段，不应再反过来大量插入前面阶段的逻辑。

---

## 7. 建议阶段对象

建议逐步引入以下结构化对象：

- `NormalizedInput`
- `ModeDecision`
- `MemoryRecallBundle`
- `PlanResult`
- `ToolExecutionBundle`
- `ResponseDraft`

这些对象可以先定义为轻量 dataclass / pydantic model，不要求第一版特别复杂。

---

## 8. 推荐实现路径

## 8.1 第一步：在 conversation_service 中显式列出六阶段

即使第一版阶段内部仍调用旧逻辑，也应先把总流程显式写出来，例如：

1. normalize_input(...)
2. detect_mode(...)
3. recall_memory(...)
4. plan_or_reason(...)
5. execute_tools(...)
6. synthesize_response(...)

这样至少结构已经稳定。

---

## 8.2 第二步：为每阶段定义输入输出对象

优先做轻量对象，避免一开始过度抽象。

要求：

- 每阶段函数签名尽量稳定
- 以 `RunContext` 为共享上下文
- 以阶段对象为结果输出

---

## 8.3 第三步：为每阶段打 trace

每阶段至少打：

- started
- finished
- failed（如适用）

这样后续可以直接做 Session Inspector。

---

## 8.4 第四步：把 Prompt / Memory / Tool / Reasoning 的挂载点固定下来

目标不是一次性完美实现，而是避免以后继续把逻辑散乱塞入 conversation service。

---

## 9. 与其他 Workstream 的关系

### 与 Workstream A 的关系
Pipeline 依赖统一的 `RunContext` 与 `SessionState`。

### 与 Workstream C 的关系
Prompt Assembly 应挂载在 Pipeline 中，而不是散落在各处。

### 与 Workstream D 的关系
Tool Runtime 应在 Stage 5 有明确调用位置。

### 与 Workstream F 的关系
Memory Recall 应在 Stage 3，Memory Write Gate 应在 Stage 6 后半段。

### 与 Workstream G / I 的关系
Reasoning 与 Workflow 都应挂载在 Stage 4，并逐步兼容可恢复执行。

---

## 10. 测试要求

至少补以下测试：

1. conversation pipeline 主路径测试
2. 六阶段顺序测试
3. 每阶段输入输出对象测试
4. `fast` 模式最小主路径测试
5. 某条包含 memory + tool 的主路径测试
6. 某阶段失败后的错误传播测试

---

## 11. 验收标准

本任务完成后，必须满足：

- 单轮运行已显式拆分为六阶段
- 各阶段已有明确函数或方法边界
- 至少三阶段已使用结构化输出对象
- conversation service 不再是纯粹的“大段内联流程”
- 每阶段已有基础 trace 事件
- 新增逻辑必须优先接到某一明确阶段中

---

## 12. 风险与注意事项

### 风险 1：阶段划分太细，第一版难落地
第一版先求边界清晰，不求内部彻底重构。

### 风险 2：Pipeline 变成只有函数名的空壳
每阶段至少应承担真实职责，不能只是把旧逻辑原封不动包一层名字。

### 风险 3：阶段之间重新共享全局状态
必须优先通过 `RunContext` 和阶段输出对象传递数据，而不是重新引入隐式共享变量。

---

## 13. 回滚方案

如果改造过程中影响过大，可以：

- 保留显式阶段框架
- 内部先通过 adapter 调旧逻辑
- 分阶段逐步替换旧实现

不允许完全回滚到“conversation service 内部一坨流程”的状态。

---

## 14. 完成后应追加的文档更新

任务完成后，需要同步更新：

- `docs/architecture/runtime-overview.md`
- `docs/architecture/conversation-pipeline.md`（建议新增）
- `docs/adr/ADR-003-conversation-pipeline.md`（建议新增）

---

## 15. 建议提交信息

可参考：

- `refactor(conversation): stage runtime into explicit pipeline`
- `feat(runtime): introduce staged conversation pipeline`
