# Backlog 014 - Skill Layer 与 Official Skill Packs

## 1. 背景

Promethea 已具备工具、记忆、推理、workspace、workflow 的长期方向，但如果没有 Skill Layer，这些能力仍然是“原材料”，而不是可直接复用、可约束、可评估的任务能力包。

Skill Layer 的作用不是简单把 prompt 包装一下，而是把一类任务的：

- 系统说明
- 工具白名单
- prompt block policy
- 示例
- 评估样例

组织成稳定可复用的能力对象。

Promethea 第一阶段不应做开放生态市场，而应做 **official curated skill packs**。

---

## 2. 目标

本任务要完成：

1. 定义统一 skill schema
2. 建立 official skill pack 组织方式
3. 让 skill 与 tools / prompt blocks / policies / evaluation 对接
4. 为后续 workflow 与 workspace 提供高层能力单元
5. 避免能力继续散落在 prompt 和 service 里

---

## 3. 非目标

本任务不负责：

- 一次性开放第三方 skill 市场
- 一次性支持复杂 skill marketplace
- 一次性实现完整 skill UI 体验

本任务重点是建立 **官方可控的 Skill Layer**。

---

## 4. 当前代码位置

优先检查：

- extensions / plugin 系统（如已存在）
- prompt 相关模块
- tool policy 相关模块
- reasoning / workflow 入口
- UI 中 potential skill selector 相关位置

---

## 5. 目标设计

## 5.1 Skill 结构

建议每个 skill 至少包含：

- `skill_id`
- `name`
- `description`
- `category`
- `system_instruction`
- `tool_allowlist`
- `prompt_block_policy`
- `default_mode`
- `examples`
- `evaluation_cases`
- `version`
- `enabled`

---

## 5.2 Skill 文件组织建议

建议每个 skill pack 目录结构如下：

- `skill.yaml`
- `system_instruction.md`
- `tool_allowlist.yaml`
- `examples.json`
- `evaluation_cases.json`

第一版可先支持本地文件形式。

---

## 5.3 第一批官方 Skills

建议先做高价值且与你项目方向强相关的官方 skill：

1. GitHub Repo Analyst
2. Project PM Assistant
3. Research Writer
4. News Tracker
5. Memory Curator
6. Coding Copilot
7. Bank Materials Assistant

---

## 6. 推荐实现路径

## 6.1 第一步：定义 SkillSchema

建议新增：

- `skills/schema.py`

至少定义：

- `SkillSpec`
- `SkillExample`
- `SkillEvaluationCase`

---

## 6.2 第二步：建立 SkillRegistry

职责：

- 加载官方 skill packs
- 校验 skill schema
- 列出可用 skills
- 根据 id 获取 skill
- 结合 user / agent / policy 决定 skill 可见性

---

## 6.3 第三步：对接 Prompt Blocks / Tool Policy

要求：

- skill 可以控制启用哪些 prompt blocks
- skill 可以限定允许哪些工具
- skill 可以指定默认 mode

---

## 6.4 第四步：为 Evaluation 留接口

每个 skill 都应有 evaluation cases，便于后续：

- 回归测试
- 模型切换测试
- prompt block 调整测试
- tool policy 调整测试

---

## 6.5 第五步：对接 UI / Selector（可渐进）

第一版可以先：

- CLI 列出 skill
- debug endpoint 查看 skill
- 在 Web UI 中做简易 selector

---

## 7. 预期效果

完成后应达到：

- 能力不再只是零散工具和 prompt
- 任务能力可打包、可约束、可评估
- 更适合 workflow、workspace、官方能力包演进
- 更适合 Codex 和工程师围绕某一 skill 做局部迭代

---

## 8. 测试要求

至少需要补以下测试：

1. SkillSchema 校验测试
2. SkillRegistry 加载测试
3. tool_allowlist 生效测试
4. prompt block policy 生效测试
5. evaluation_cases 读取测试
6. 某个官方 skill 主路径测试

---

## 9. 验收标准

本任务完成后，必须满足：

- 已存在 SkillSpec 与 SkillRegistry
- 已能加载至少一个官方 skill pack
- skill 能限定 tool allowlist
- skill 能影响 prompt block policy 或默认 mode
- 已有 evaluation cases 结构
- 新的官方任务能力优先通过 skill 而不是散乱逻辑实现

---

## 10. 风险与注意事项

### 风险 1：把 skill 做成另一层 prompt 黑盒
必须确保 skill 与 tool policy、prompt blocks、evaluation 三者都有明确连接。

### 风险 2：一开始就做开放生态
第一阶段坚持官方 curated packs，先把治理模型做好。

### 风险 3：skill 与 workflow 功能重叠不清
skill 是“能力包”；workflow 是“执行流程”。两者可以组合，但不应混淆。

---

## 11. 回滚方案

如果接入影响过大，可以：

- 保留 SkillSchema 与 Registry
- 先只实现少数官方 skill
- 先通过 debug endpoint 使用 skill
- UI 后续再补

不允许回滚到“所有能力都散落在系统提示和 service 中”的状态。

---

## 12. 完成后应追加的文档更新

- `docs/architecture/skill-layer.md`（建议新增）
- `docs/adr/ADR-014-skill-layer.md`（建议新增）

---

## 13. 建议提交信息

- `feat(skills): introduce skill layer and curated official packs`
- `refactor(runtime): package task capabilities into structured skills`
