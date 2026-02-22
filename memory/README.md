# Memory Module

---

## 中文文档

### 1. 模块目标

`memory` 模块负责把“对话原文”转成“可长期使用的结构化记忆”，并在未来对话中按需召回。

核心目标：
- 写得进（稳定写入）
- 找得到（有效召回）
- 养得住（聚类、摘要、遗忘维护）

### 2. 关键文件

- `memory/adapter.py`：对外统一入口（与 gateway 对接）
- `memory/hot_layer.py`：近时写入与基础入图
- `memory/warm_layer.py`：概念聚类与稳定化
- `memory/cold_layer.py`：摘要压缩与长期沉淀
- `memory/forgetting.py`：时间衰减与清理策略
- `memory/auto_recall.py`：召回检索与层级排序
- `memory/llm_extractor.py`：事实/实体抽取
- `memory/session_scope.py`：用户作用域与会话作用域工具
- `memory/neo4j_connector.py`：Neo4j 访问封装
- `memory/models.py`：节点与关系模型

### 3. 架构与工作流

写入路径：
1. 用户与助手完成一轮交互
2. 抽取器提取 facts/entities
3. 写入 Hot 层节点
4. 异步触发 Warm 聚类与 Cold 摘要
5. 遗忘机制按策略衰减与清理

召回路径：
1. 根据当前 query 判断是否触发 recall
2. 在同一用户全量记忆里检索
3. 分层聚合（summary/concept/direct/related/recent）
4. 结果注入上下文参与回复生成

### 4. 示例

会话 A：用户说“我叫王二，今年 26 岁”。  
会话 B：用户问“我今年几岁？”  
如果写入和召回正常，系统应在跨会话 recall 中命中该事实并回答 26 岁。

### 5. 使用注意事项

- 记忆隔离是按用户，不是按会话
- recall 结果应服务“超出上下文窗口”的信息补足
- LLM 抽取失败不应导致主对话失败

### 6. 修改注意事项

- 改 `auto_recall.py` 时先明确召回优先级目标
- 改 Cypher 时注意不存在关系/属性的告警
- 改遗忘策略后回归 `test_memory_forgetting_regressions.py`

---

## English Documentation

### 1. Purpose

The `memory` module transforms raw conversation turns into long-lived structured memory and recalls relevant information in future turns.

Goals:
- reliable writes
- useful retrieval
- sustainable maintenance (cluster/summary/forgetting)

### 2. Key Files

- `memory/adapter.py`: external entrypoint integrated with gateway
- `memory/hot_layer.py`: near-term memory write path
- `memory/warm_layer.py`: clustering and stabilization
- `memory/cold_layer.py`: summarization/compression
- `memory/forgetting.py`: decay and cleanup policy
- `memory/auto_recall.py`: retrieval logic and layer ranking
- `memory/llm_extractor.py`: fact/entity extraction
- `memory/session_scope.py`: user/session scoping helpers
- `memory/neo4j_connector.py`: Neo4j access wrapper
- `memory/models.py`: graph node/edge models

### 3. Architecture & Flow

Write path:
1. A full user-assistant turn completes
2. Extractor produces facts/entities
3. Hot-layer nodes are persisted
4. Warm clustering and cold summarization run asynchronously
5. Forgetting pass applies decay/cleanup

Recall path:
1. Decide whether recall should run
2. Search user-wide memory
3. Aggregate multi-layer results (summary/concept/direct/related/recent)
4. Inject into model context

### 4. Example

Session A: user says “My name is Wang Er, I am 26.”  
Session B: user asks “How old am I?”  
If write+recall pipeline is healthy, cross-session recall should retrieve age=26.

### 5. Operational Notes

- isolation boundary is user-level, not session-level
- recall should primarily solve long-horizon context gaps
- extraction failures should not crash primary chat flow

### 6. Change Notes

- define ranking intent before changing `auto_recall.py`
- handle Neo4j missing relationship/property warnings carefully
- run forgetting regressions after decay policy changes
