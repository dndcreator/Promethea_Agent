# Backlog 015 - Config Schema 与 Migration 治理

## 1. 背景

Promethea 未来会逐步引入更多能力：

- multi-user
- tool policy
- workspace
- workflow
- skills
- channel adapters
- audit / doctor
- reasoning modes

随着配置项增长，配置系统本身会成为潜在高风险点。如果没有统一 schema 与 migration 机制，会出现：

- 新旧配置不兼容
- 用户配置升级失败
- 配置 typo 导致系统不可用
- 超大配置对象进入上下文污染 prompt
- 运行时配置与用户偏好配置混在一起

本任务负责建立配置治理基础。

---

## 2. 目标

本任务要完成：

1. 建立配置 schema version 概念
2. 建立配置 migration 机制
3. 建立 deprecation warning 机制
4. 区分不同类型配置
5. 限制超大配置对象污染 runtime / prompt

---

## 3. 非目标

本任务不负责：

- 一次性重写全部配置系统
- 一次性做完配置 UI
- 一次性支持所有复杂配置源同步

本任务重点是建立 **配置演进与治理的最低骨架**。

---

## 4. 当前代码位置

优先检查：

- config 相关文件
- 用户配置加载逻辑
- environment variable 注入逻辑
- `config_service`
- 任何 schema / validation 相关代码
- 任何会把配置注入 prompt 或 runtime 的地方

---

## 5. 目标设计

## 5.1 Config Version

所有持久化配置应至少包含：

- `config_version`

用来支持：

- migration
- compatibility check
- downgrade / fallback decision

---

## 5.2 配置分类建议

至少区分：

### 运行时系统配置
例如：
- model provider defaults
- gateway settings
- tracing / audit settings
- workspace root defaults

### 用户偏好配置
例如：
- default mode
- preferred skills
- prompt / persona toggles
- personal tool visibility

### 安全配置
例如：
- secrets references
- permission defaults
- sandbox policies

### 渠道配置
例如：
- channel credentials
- webhook / bot settings
- streaming options

---

## 5.3 Migration 目标

配置升级时应支持：

- 旧 schema -> 新 schema 的转换
- 缺失字段补默认值
- 废弃字段标记 warning
- 无法安全迁移时给出明确错误

---

## 5.4 Scoped Query 原则

配置查询不应默认返回巨大的全量对象。

建议支持：

- `get_runtime_config(scope=...)`
- `get_user_preferences(user_id, scope=...)`
- `get_tool_policy_config(user_id, agent_id)`
- `get_channel_config(channel_id)`

避免把巨量 schema 或无关配置塞入单轮运行上下文。

---

## 6. 推荐实现路径

## 6.1 第一步：定义配置 schema version

在现有配置根对象中加入 `config_version`。

---

## 6.2 第二步：建立 migration 模块

建议新增：

- `config/migrations.py`

职责：

- 注册 migration steps
- 判断当前配置版本
- 执行逐步迁移
- 输出 warning / report

---

## 6.3 第三步：建立配置访问层

避免各模块直接随手读原始配置文件。  
建议统一通过：

- `config_service`
- 或专门 config accessor 层

实现 scoped query。

---

## 6.4 第四步：区分 runtime-config 与 user-preferences

要求：

- 不同类型配置在结构上有边界
- 避免一锅端给 runtime pipeline

---

## 6.5 第五步：增加 deprecation warning

当读取旧字段或废弃字段时：

- 记录 warning
- 在 doctor / audit 中可见
- 必要时在 migration report 中输出

---

## 7. 预期效果

完成后应达到：

- 配置演进可控
- 新增模块不容易把配置系统搞乱
- 减少因为 schema 变化导致整体不可用的风险
- 避免超大 config 污染 runtime / prompt
- 为 doctor 与 multi-user 配置管理提供基础

---

## 8. 测试要求

至少需要补以下测试：

1. config_version 存在测试
2. migration from old version 测试
3. deprecated field warning 测试
4. scoped query 测试
5. 运行时配置与用户偏好配置分离测试
6. 配置错误时的明确异常测试

---

## 9. 验收标准

本任务完成后，必须满足：

- 已存在 `config_version`
- 已存在 migration 机制
- 已支持 deprecation warning
- 配置查询至少部分支持 scope 化
- 运行时配置与用户偏好配置开始结构分离
- 不再默认把庞大配置对象直接注入 runtime

---

## 10. 风险与注意事项

### 风险 1：一开始试图统一全部配置，工程量过大
第一版先收最关键配置边界，不要求一次性彻底统一一切。

### 风险 2：migration 只是文档，没有真正执行
必须至少让一条旧版本配置迁移路径真正可运行。

### 风险 3：配置访问层与原始读取并存太久
允许过渡期，但新逻辑必须优先走统一访问层。

---

## 11. 回滚方案

如改造影响过大，可以：

- 保留 config_version 与 migration 模块
- 先只让部分配置走新 schema
- 逐步将旧读取逻辑迁移到 config_service / accessor

不允许回滚到完全无版本、无迁移、无边界的状态。

---

## 12. 完成后应追加的文档更新

- `docs/architecture/config-model.md`（建议新增）
- `docs/adr/ADR-015-config-schema-and-migration.md`（建议新增）

---

## 13. 建议提交信息

- `feat(config): introduce schema versioning and migration`
- `refactor(config): split runtime config user preferences and scoped access`
