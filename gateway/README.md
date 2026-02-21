# Gateway 使用说明

`gateway` 是系统的运行编排层，负责：
- 协议处理（WebSocket 请求/响应）
- 事件总线
- 会话任务排队与重试
- 调用 Tool/Memory/Conversation/Config 四类服务

## 核心组件

```text
gateway/
├─ server.py              # GatewayServer
├─ protocol.py            # 请求/事件协议
├─ events.py              # EventEmitter
├─ connection.py          # 连接管理
├─ conversation_service.py
├─ memory_service.py
├─ tool_service.py
└─ config_service.py
```

## 运行模型

1. 客户端发送请求到 Gateway
2. Gateway 解析请求并路由到对应 Service
3. Service 执行业务逻辑
4. 结果通过响应或事件返回

## 会话处理机制

`conversation_service.py` 已实现：
- 按 session 的队列化处理
- 可配置重试次数和重试间隔
- worker 空闲自动回收
- 回合原子提交（begin/commit/abort）

## 用户隔离（Gateway 侧）

- 默认优先用连接身份（device/session 绑定）解析用户。
- 会话相关请求会做会话归属校验。
- 记忆相关请求会在调用前校验当前用户是否拥有该 session。

## 记忆事件流

- `interaction.completed` 触发记忆候选提取
- 候选经过去重和变更检测后写入图
- 后续触发 warm/cold/forgetting 维护

## 常用请求类型

见 `protocol.py`：
- `memory.query`
- `memory.cluster`
- `memory.summarize`
- `memory.graph`
- `sessions.list`
- `session.detail`
- `followup`
- `config.*`

## 调试建议

1. 开启 info 日志观察请求链路。
2. 先验证 sessions，再验证 memory，最后验证工具调用。
3. 遇到隔离问题先查 user_id 解析和 session 归属。
