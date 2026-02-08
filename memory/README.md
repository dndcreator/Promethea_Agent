# Memory 模块

记忆系统是 Promethea Agent 的核心能力之一，基于 Neo4j 实现**三层记忆架构**。

## 架构设计

```
┌─────────────────────────────────────────┐
│          MemoryAdapter (适配器)          │
│  统一接口，适配对话系统和记忆系统          │
└─────────────────────────────────────────┘
              │
    ┌─────────┼─────────┬──────────────┐
    ▼         ▼         ▼              ▼
Hot Layer  Warm Layer  Cold Layer   Forgetting
(热层)      (温层)      (冷层)        (遗忘层)
```

## 三层记忆系统

### 1. Hot Layer (热层) - `hot_layer.py`

- **职责**: 实时提取结构化信息
- **功能**:
  - 从消息中提取实体（Entity）
  - 提取事实元组（Fact Tuple）：`(主体, 关系, 客体, 时间, 置信度)`
  - 实时存储到 Neo4j
- **特点**: 
  - 低延迟，实时处理
  - 结构化存储，便于查询

### 2. Warm Layer (温层) - `warm_layer.py`

- **职责**: 异步语义聚类
- **功能**:
  - 将热层的实体聚类成概念（Concept）
  - 使用 Embedding 模型计算相似度
  - 自动发现实体间的关联
- **特点**:
  - 异步处理，不阻塞对话
  - 可配置聚类阈值和最小聚类大小

### 3. Cold Layer (冷层) - `cold_layer.py`

- **职责**: 长期记忆压缩和摘要
- **功能**:
  - 当消息数量达到阈值时，生成会话摘要
  - 压缩历史消息，保留关键信息
  - 支持增量摘要和全量摘要
- **特点**:
  - 节省存储空间
  - 保留长期记忆的关键信息

### 4. Forgetting Layer (遗忘层) - `forgetting.py`

- **职责**: 记忆衰减和清理
- **功能**:
  - 基于时间的记忆衰减
  - 清理已遗忘的记忆节点
  - 保持记忆系统的健康

## 核心组件

### MemoryAdapter (`adapter.py`)

- **职责**: 适配器，统一记忆系统接口
- **功能**:
  - 适配 `MessageManager` 的简单接口到复杂的三层记忆系统
  - 自动触发温层聚类、冷层摘要、遗忘层清理
  - 提供记忆召回接口

### Neo4jConnector (`neo4j_connector.py`)

- **职责**: Neo4j 数据库连接管理
- **功能**:
  - 连接池管理
  - 查询封装
  - 事务处理

### LLMExtractor (`llm_extractor.py`)

- **职责**: 使用 LLM 提取结构化信息
- **功能**:
  - 从消息中提取实体和关系
  - 支持指代消解
  - 时间规范化

### AutoRecall (`auto_recall.py`)

- **职责**: 自动记忆召回
- **功能**:
  - 根据查询自动召回相关记忆
  - 构建上下文供 LLM 使用

## 使用示例

### 初始化记忆系统

```python
from memory.adapter import MemoryAdapter

adapter = MemoryAdapter()
if adapter.is_enabled():
    print("记忆系统已启用")
```

### 保存消息到记忆

```python
adapter.add_message(
    session_id="session_123",
    role="user",
    content="我叫张三，喜欢编程",
    user_id="user_123"
)
```

### 查询记忆

```python
context = adapter.get_context(
    query="用户喜欢什么？",
    session_id="session_123",
    user_id="user_123"
)
```

### 手动触发聚类

```python
from memory import create_warm_layer_manager

warm_layer = create_warm_layer_manager(adapter.hot_layer.connector)
concepts = warm_layer.cluster_entities("session_123")
```

## 配置

记忆系统配置在 `config/default.json` 中：

```json
{
  "memory": {
    "enabled": true,
    "neo4j": {
      "uri": "bolt://localhost:7687",
      "username": "neo4j",
      "password": "password"
    },
    "hot_layer": {
      "max_tuples_per_message": 10,
      "min_confidence": 0.5
    },
    "warm_layer": {
      "enabled": true,
      "clustering_threshold": 0.7
    },
    "cold_layer": {
      "compression_threshold": 50
    }
  }
}
```

## 数据模型

### Neo4j 节点类型

- `Message` - 消息节点
- `Entity` - 实体节点
- `Concept` - 概念节点（温层聚类结果）
- `Summary` - 摘要节点（冷层生成）
- `Session` - 会话节点

### 关系类型

- `PART_OF_SESSION` - 属于会话
- `HAS_ENTITY` - 包含实体
- `RELATED_TO` - 相关关系
- `CLUSTERED_INTO` - 聚类到概念

## 性能优化

1. **异步处理**: 温层聚类、冷层摘要都是异步执行
2. **连接池**: Neo4j 连接使用连接池，避免频繁创建连接
3. **缓存**: 会话级别的消息缓存，减少数据库查询
4. **批量操作**: 支持批量插入和查询

## 相关文档

- [主 README](../README.md)
- [架构文档](../docs/ARCHITECTURE.md)
- [Gateway MemoryService](../gateway/README.md#memoryservice)
