# API Server 模块

API Server 提供 HTTP REST API 接口，用于 Web UI 和外部系统集成。

## 架构设计

```
┌─────────────────────────────────────┐
│      FastAPI Application            │
│  - HTTP REST API                  │
│  - Server-Sent Events (SSE)           │
└─────────────────────────────────────┘
              │
    ┌─────────┼─────────┬─────────┐
    ▼         ▼         ▼         ▼
Chat    Sessions  Memory  Config  Doctor
Routes  Routes    Routes  Routes  Routes
```

## 核心组件

### 1. Server (`server.py`)

- **职责**: FastAPI 应用入口和生命周期管理
- **功能**:
  - 应用启动和关闭
  - 中间件配置
  - 路由注册
  - 插件系统初始化

### 2. Routes (路由模块)

#### Chat Routes (`routes/chat.py`)
- `POST /api/chat` - 发送消息（支持 SSE 流式响应）
- 工具调用事件推送
- 响应去重处理

#### Sessions Routes (`routes/sessions.py`)
- `GET /api/sessions` - 列出所有会话
- `GET /api/sessions/{session_id}` - 获取会话详情
- `DELETE /api/sessions/{session_id}` - 删除会话

#### Memory Routes (`routes/memory.py`)
- `POST /api/memory/query` - 查询记忆
- `POST /api/memory/cluster` - 触发聚类
- `POST /api/memory/summarize` - 触发摘要

#### Config Routes (`routes/config.py`)
- `GET /api/config` - 获取配置
- `POST /api/config/update` - 更新配置
- `POST /api/config/reset` - 重置配置
- `POST /api/config/switch-model` - 切换模型

#### Doctor Routes (`routes/doctor.py`)
- `GET /api/doctor` - 系统诊断
- `POST /api/doctor/migrate-config` - 配置迁移

#### Auth Routes (`routes/auth.py`)
- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录

### 3. MessageManager (`message_manager.py`)

- **职责**: 会话和消息管理
- **功能**:
  - 创建和管理会话
  - 消息历史存储
  - 与记忆系统集成

### 4. UserManager (`user_manager.py`)

- **职责**: 用户管理
- **功能**:
  - 用户注册和认证
  - 用户配置管理
  - 用户与通道账号绑定

### 5. SessionStore (`session_store.py`)

- **职责**: 会话持久化
- **功能**:
  - 会话数据保存到 `sessions.json`
  - 原子写入，防止数据损坏

## API 端点

### 聊天相关

```http
POST /api/chat
Content-Type: application/json

{
  "message": "你好",
  "session_id": "session_123",
  "user_id": "user_123"
}
```

响应：Server-Sent Events 流

### 会话管理

```http
GET /api/sessions
GET /api/sessions/{session_id}
DELETE /api/sessions/{session_id}
```

### 配置管理

```http
GET /api/config
POST /api/config/update
POST /api/config/reset
POST /api/config/switch-model
```

### 系统诊断

```http
GET /api/doctor
POST /api/doctor/migrate-config
```

## Server-Sent Events (SSE)

聊天接口支持 SSE 流式响应，实时推送：

- `text` - 文本块
- `tool_detected` - 工具调用检测
- `tool_start` - 工具开始执行
- `tool_result` - 工具执行结果
- `tool_error` - 工具执行错误
- `done` - 完成

## 使用示例

### 启动服务器

```python
from api_server.server import app
import uvicorn

uvicorn.run(app, host="0.0.0.0", port=8000)
```

### 客户端调用

```python
import requests

# 发送消息
response = requests.post(
    "http://localhost:8000/api/chat",
    json={
        "message": "你好",
        "session_id": "session_123"
    },
    stream=True
)

# 处理 SSE 流
for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))
```

## 状态管理

### State (`state.py`)

全局状态管理，存储：
- `conversation` - 对话核心实例
- `memory_adapter` - 记忆适配器
- `agent_manager` - Agent 管理器

## 安全考虑

1. **用户认证**: 使用 JWT Token 或 Session
2. **API Key 保护**: 敏感信息不通过 API 暴露
3. **输入验证**: 使用 Pydantic 模型验证
4. **CORS 配置**: 限制跨域访问

## 相关文档

- [主 README](../README.md)
- [Gateway 模块](../gateway/README.md)
- [配置管理](../config/README.md)
