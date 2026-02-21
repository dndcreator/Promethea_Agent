# Quick Start（手把手）

本文面向第一次使用 Promethea Agent 的用户，按步骤执行即可跑通。

## 第 0 步：准备环境

请确认：
1. 已安装 Python 3.10+
2. 已安装并启动 Neo4j Desktop（如果你要启用记忆）
3. 当前目录在项目根目录（`Agent/`）

## 第 1 步：安装依赖

```powershell
pip install -r requirements.txt
```

如果你希望以开发模式安装：

```powershell
pip install -e .
```

## 第 2 步：配置 `.env`

在项目根目录新建 `.env`（可从 `env.example` 复制）。

最小可用配置：

```env
API__API_KEY=你的Key
API__BASE_URL=https://openrouter.ai/api/v1
API__MODEL=nvidia/nemotron-3-nano-30b-a3b:free
```

如果要启用记忆，再加：

```env
MEMORY__ENABLED=true
MEMORY__NEO4J__ENABLED=true
MEMORY__NEO4J__URI=bolt://127.0.0.1:7687
MEMORY__NEO4J__USERNAME=neo4j
MEMORY__NEO4J__PASSWORD=你的密码
MEMORY__NEO4J__DATABASE=neo4j
```

## 第 3 步：启动服务

```powershell
python start_gateway_service.py
```

启动后访问：
- `http://127.0.0.1:8000/UI/index.html`

## 第 4 步：注册并登录

1. 在 UI 注册账号
2. 登录进入对话页
3. 发一条测试消息

## 第 5 步：验证记忆是否生效（可选）

1. 连续聊几轮，包含可记忆信息（偏好、目标、身份、约束）
2. 继续提问看是否能召回上下文
3. 打开记忆相关接口（或 UI 功能）检查图数据

## 第 6 步：验证“用户隔离”

1. 用 A 账号创建会话并写入明显信息
2. 退出后用 B 账号登录
3. B 不应看到 A 的会话、记忆和日志

日志路径示例：
- `logs/<A_user_id>/YYYY-MM-DD.log`
- `logs/<B_user_id>/YYYY-MM-DD.log`

## 常见报错定位

### `API key is not configured`

说明 `API__API_KEY` 未配置或为空。

### `Memory system not enabled`

说明 `MEMORY__ENABLED` 或 `MEMORY__NEO4J__ENABLED` 未开启。

### Neo4j 连接失败

重点检查：
1. Neo4j 是否真的启动
2. 端口和 URI 是否正确（通常 `7687`）
3. 用户名/密码/数据库名是否正确

## Demo 前建议

1. 固定模型与提示词
2. 用 1-2 个预设账号做演示
3. 提前预热几条可展示的记忆样本
