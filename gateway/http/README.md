# Gateway HTTP Module

---

## 中文文档

### 1. 模块功能

`gateway/http` 是 API 边界层，负责：
- API 路由与参数入口
- 身份认证与用户上下文解析
- 请求级中间件（限流、日志、错误归一）
- 用户配置与会话数据的 HTTP 访问

### 2. 主要文件

- `gateway/http/router.py`：路由注册入口
- `gateway/http/middleware.py`：上下文、限流、日志、异常标准化
- `gateway/http/user_manager.py`：用户与用户配置文件读写
- `gateway/http/message_manager.py`：会话消息存储
- `gateway/http/routes/auth.py`：注册、登录、用户信息
- `gateway/http/routes/chat.py`：对话接口（含流式）
- `gateway/http/routes/config.py`：配置查询与更新
- `gateway/http/routes/memory.py`：记忆接口与图可视化数据
- `gateway/http/routes/sessions.py`：会话列表与详情

### 3. 请求工作流

1. 进入 middleware
2. 解析 token 得到 `user_id`
3. 执行 route 业务逻辑
4. 返回统一结构的成功/失败响应

### 4. 示例：配置保存

1. 前端提交设置
2. 调 `POST /api/config/update`
3. route 调 `ConfigService.update_user_config`
4. `user_manager` 持久化到 `config/users/<user_id>/config.json`

### 5. 使用注意事项

- 避免同一动作调用多个保存接口（双写）
- 错误返回对用户应可读，对日志应可追踪
- 鉴权失败和业务失败要区分清楚状态码

### 6. 修改注意事项

- 新接口命名保持一致风格（`/api/<domain>/<action>`）
- 改中间件时确认不会影响流式响应
- 修改 auth 字段后同步更新前端登录态逻辑

---

## English Documentation

### 1. Purpose

`gateway/http` is the API boundary layer responsible for:
- routing and request entry
- auth and user context resolution
- middleware concerns (rate limit, logs, normalized errors)
- HTTP access to user/session/config/memory operations

### 2. Main Files

- `gateway/http/router.py`: route assembly
- `gateway/http/middleware.py`: context/rate-limit/log/error handling
- `gateway/http/user_manager.py`: user and user-config persistence
- `gateway/http/message_manager.py`: session message storage
- `gateway/http/routes/auth.py`: register/login/profile
- `gateway/http/routes/chat.py`: chat endpoints (including streaming)
- `gateway/http/routes/config.py`: config APIs
- `gateway/http/routes/memory.py`: memory endpoints and graph payloads
- `gateway/http/routes/sessions.py`: session list/details

### 3. Request Flow

1. Middleware runs first
2. Token resolves into `user_id`
3. Route executes domain logic
4. Response is normalized for client consumption

### 4. Example: Settings Save

1. UI submits settings
2. Calls `POST /api/config/update`
3. Route delegates to `ConfigService.update_user_config`
4. `user_manager` persists to `config/users/<user_id>/config.json`

### 5. Operational Notes

- Avoid duplicate write paths for the same action
- Keep user-facing errors readable and logs actionable
- Distinguish auth failures from business failures via status codes

### 6. Change Notes

- Keep endpoint naming consistent
- Re-verify streaming behavior after middleware changes
- Sync frontend auth state handling when auth payload fields change
