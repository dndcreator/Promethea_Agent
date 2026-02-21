# 配置说明

本项目采用“默认配置 + 用户配置 + 环境变量”的分层配置模型。

## 配置来源与优先级

从低到高：
1. `config/default.json`（系统默认）
2. `config/users/<user_id>/config.json`（用户非敏感配置）
3. `.env` / 系统环境变量（敏感配置优先）

## 当前安全策略

- API Key 等敏感信息：只放 `.env`（全局共享）
- 用户配置文件：仅存非敏感项（如 agent 名称、系统提示词等）

## 常用环境变量（示例）

```env
API__API_KEY=...
API__BASE_URL=https://openrouter.ai/api/v1
API__MODEL=nvidia/nemotron-3-nano-30b-a3b:free

MEMORY__ENABLED=true
MEMORY__NEO4J__ENABLED=true
MEMORY__NEO4J__URI=bolt://127.0.0.1:7687
MEMORY__NEO4J__USERNAME=neo4j
MEMORY__NEO4J__PASSWORD=...
MEMORY__NEO4J__DATABASE=neo4j
```

## 用户配置文件位置

```text
config/
├─ default.json
└─ users/
   └─ <user_id>/
      └─ config.json
```

## 常见问题

### 1) 为什么用户配置里改了 api 仍不生效

因为当前策略是全局 `.env` 控制敏感 key，用户配置中的敏感字段会被过滤。

### 2) 如何恢复默认配置

可通过配置接口 reset，或手动删除对应用户配置文件后重启服务。
