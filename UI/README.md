# UI Module

## 中文

### 模块定位

`UI` 是 Promethea 的 Web 产品界面，负责：

- 登录与用户状态展示
- 会话列表和聊天渲染
- 流式响应（SSE）展示
- 设置面板与配置保存
- 记忆工作台入口
- 推理可视化（ToT/ReAct）与纠偏/中止控制
- 开源发布展示面板（Showcase）

### 核心文件

- `UI/index.html`：页面结构与各类 modal
- `UI/style.css`：布局和视觉样式
- `UI/script.js`：交互逻辑（聊天、SSE、设置、i18n、展示面板）

### 页面流程

1. 页面加载并检查认证状态
2. 初始化用户、会话、状态轮询
3. 发送消息到 `/api/chat`
4. 根据流式或非流式结果更新聊天内容
5. 若存在推理树，轮询 `/api/reasoning/tree/{tree_id}` 并展示状态

## English

### Purpose

`UI` is the web product shell for Promethea. It provides:

- auth and user/session state
- chat and streaming response rendering
- settings and config update surface
- memory workbench entry
- reasoning visualization with steer/stop controls
- launch-ready showcase panel for demos

### Key Files

- `UI/index.html`: main layout and modal structure
- `UI/style.css`: styling and layout system
- `UI/script.js`: behavior (chat, SSE, settings, i18n, showcase)

### Main Flow

1. load page and verify authentication
2. initialize user/session/status polling
3. send chat request to `/api/chat`
4. render SSE or non-stream response
5. if reasoning tree exists, poll `/api/reasoning/tree/{tree_id}` for live visualization
