# UI Module

---

## 中文文档

### 1. 模块定位

`UI` 是项目的 Web 前端，负责：
- 登录与用户状态展示
- 会话列表与对话区渲染
- 流式响应显示
- 设置面板与配置保存
- 记忆图可视化入口

### 2. 文件说明

- `UI/index.html`：页面结构
- `UI/style.css`：样式与布局
- `UI/script.js`：交互逻辑（聊天、设置、SSE、i18n）

### 3. 页面工作流

1. 页面加载 -> 检查登录态
2. 初始化状态（用户、会话、配置按钮状态）
3. 发送消息 -> 调 `/api/chat`
4. 按流式或普通模式渲染回复
5. 更新会话侧栏和当前会话内容

### 4. 示例：设置保存

1. 用户在设置面板修改参数
2. 前端整理配置对象
3. 调用统一接口 `POST /api/config/update`
4. 保存成功后关闭设置面板并更新本地展示状态

### 5. 使用注意事项

- 旧消息加载应一次性渲染，不要伪流式回放
- 流式失败时要有 JSON fallback
- 文案必须走 i18n，避免硬编码中英文

### 6. 修改注意事项

- 改 streaming 逻辑时同时测：正常 SSE / 网络抖动 / 非流式 fallback
- 改设置表单时同步后端 schema
- 改用户显示逻辑时验证登录、自动登录、退出三条路径

---

## English Documentation

### 1. Purpose

`UI` is the web frontend for:
- auth and user state display
- session list and chat rendering
- streaming response visualization
- settings panel and config save
- memory graph entrypoint

### 2. Files

- `UI/index.html`: structure
- `UI/style.css`: styling/layout
- `UI/script.js`: interactions (chat/settings/SSE/i18n)

### 3. Page Flow

1. page load -> auth check
2. initialize user/session/UI state
3. send message -> call `/api/chat`
4. render response via streaming or non-stream fallback
5. update session sidebar and active transcript

### 4. Example: Settings Save

1. user edits settings fields
2. frontend builds normalized config payload
3. calls `POST /api/config/update`
4. closes modal and refreshes visible state on success

### 5. Notes

- historical messages should render directly (no fake stream replay)
- maintain JSON fallback for streaming failures
- all user-facing text should be i18n-driven

### 6. Change Notes

- test SSE, degraded network, and fallback paths when changing streaming code
- sync backend schema when changing settings form fields
- validate login/auto-login/logout flows when changing user-state UI
