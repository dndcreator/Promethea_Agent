# Memory 模块使用说明

`memory` 是基于 Neo4j 的图记忆系统，支持多层记忆与长期维护。

## 目标

- 记录用户长期有价值信息
- 在对话中按需召回
- 控制记忆成本（去重、聚类、摘要、遗忘）

## 架构

```text
MemoryAdapter
├─ Hot Layer      # 实时抽取与入图
├─ Warm Layer     # 概念聚类
├─ Cold Layer     # 摘要压缩
└─ Forgetting     # 时间衰减与清理
```

## 关键文件

- `adapter.py`：对外统一入口
- `hot_layer.py`：消息抽取与图写入
- `warm_layer.py`：概念聚类
- `cold_layer.py`：会话摘要
- `forgetting.py`：衰减与清理
- `auto_recall.py`：召回
- `neo4j_connector.py`：图数据库访问
- `session_scope.py`：用户作用域会话工具

## 用户隔离设计（重点）

- 记忆会话 ID 使用 `user_id::session_id` 逻辑作用域。
- Session 节点与 User 节点存在 `OWNED_BY` 关系。
- 查询时必须校验“该 session 是否属于当前 user”。
- 同名 session 在不同用户下不会共享记忆。

## 写入流程

1. 监听一轮完整交互（用户输入 + 助手输出）
2. 记忆分类器判断是否值得写入
3. 去重（内容级 + 图级语义检测）
4. 写入 Hot Layer
5. 异步触发 warm/cold/forgetting 维护

## 召回流程

1. 对当前 query 做轻量判断（是否值得召回）
2. 必要时使用模型判定 recall
3. 在当前用户作用域内检索图数据
4. 组装上下文拼接到 system prompt

## 配置项（常用）

- `memory.enabled`
- `memory.neo4j.*`
- `memory.api.use_main_api`
- `memory.api.api_key/base_url/model`（可选独立记忆模型）
- `memory.warm_layer.*`
- `memory.cold_layer.*`
- `memory.gating.*`

## 本地连通检查

1. Neo4j Desktop 数据库已启动
2. `.env` 中 `MEMORY__NEO4J__*` 正确
3. 应用日志无连接异常
4. 触发一轮对话后，图中出现 `session_*`、`message_*` 节点

## 常见问题

### 1) 写入了但召回不到

先查 recall gating 阈值是否过严，再看 query 是否被判定为无需召回。

### 2) warm/cold 层不触发

通常是消息量未达到阈值，或维护任务间隔尚未到达。

### 3) 想单独给记忆配置模型

将 `memory.api.use_main_api=false`，并填写 `memory.api` 三项。
