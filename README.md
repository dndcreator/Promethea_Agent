# Promethea Agent

Promethea Agent is a local-first, multi-user AI assistant system with:
- gateway-first service architecture
- graph memory (Neo4j, Hot/Warm/Cold)
- pluggable channels and tools
- web UI + HTTP API

---

## 中文文档

### 1. 项目定位

Promethea Agent 的目标是：在一套清晰的工程架构里，把“对话、工具、记忆、配置、用户隔离”整合起来，做到：
- 能直接跑起来
- 能看懂模块边界
- 能稳定扩展

它不是只做一个聊天页面，而是一套可持续演进的 Agent 基础设施。

### 2. 核心能力

- 对话能力：支持会话管理与流式回复
- 记忆能力：基于 Neo4j 的多层记忆系统（Hot/Warm/Cold）
- 用户隔离：按 `user_id` 隔离配置、会话、记忆
- 插件扩展：通过 `core/plugins` + `extensions/*` 按规范扩展渠道与服务
- 工具调用：支持本机能力与 Web 搜索

### 3. 目录结构（开发者视角）

```text
Agent/
├─ gateway/            # 网关运行时与服务编排
├─ gateway/http/       # HTTP API 边界层（路由/中间件/用户与会话管理）
├─ memory/             # 记忆系统（写入、维护、召回）
├─ core/               # 插件系统骨架（发现、加载、注册）
├─ channels/           # 多渠道消息接入层
├─ computer/           # 本机操作能力封装
├─ agentkit/           # MCP 与工具调用框架
├─ extensions/         # 插件实现
├─ UI/                 # 前端页面与交互逻辑
├─ config/             # 默认配置与用户配置目录
├─ tests/              # 测试与回归
└─ start_gateway_service.py
```

### 4. 一次完整请求的工作流

以“用户在 Web UI 发一条消息”为例：

1. 前端调用 `/api/chat`
2. HTTP 中间件解析用户身份并注入上下文
3. 对话核心读取用户配置，调用 LLM 生成回复
4. 回复写入会话存储
5. 记忆系统接收候选消息，进行抽取/聚类/总结/遗忘维护
6. 下次对话如果触发 recall，会在同一用户的全量记忆中检索并注入上下文

### 5. 快速开始

1. 安装依赖

```powershell
pip install -r requirements.txt
```

2. 准备 `.env`（至少配置主模型 API）

3. 启动服务

```powershell
python start_gateway_service.py
```

4. 打开页面
- API: `http://127.0.0.1:8000`
- UI: `http://127.0.0.1:8000/UI/index.html`

### 6. 给用户的使用建议

- 记忆是“按用户全局”生效，不是只在单会话里生效
- 如果上游模型限流（429），主对话应看到可读提示，不应看到裸堆栈
- 修改设置后应通过统一接口保存（推荐 `POST /api/config/update`）

### 7. 给开发者的修改建议

- 先保持边界：Route -> Service -> Storage，不要跳层
- 配置改动集中到 `ConfigService`，不要多入口双写
- 记忆算法改动后务必跑回归测试
- 前端改流式逻辑时同时验证 SSE 与 JSON fallback

### 8. 模块文档索引

- `gateway/README.md`
- `gateway/http/README.md`
- `memory/README.md`
- `core/README.md`
- `channels/README.md`
- `computer/README.md`
- `agentkit/README.md`
- `extensions/README.md`
- `UI/README.md`
- `config/README.md`
- `tests/README.md`

---

## English Documentation

### 1. Project Overview

Promethea Agent is designed as a maintainable AI-agent infrastructure that combines chat, tools, memory, config, and user isolation in one coherent architecture.

Goals:
- easy to run
- easy to understand
- safe to extend

### 2. Core Capabilities

- Chat with session management and streaming
- Graph memory on Neo4j (Hot/Warm/Cold)
- Strong `user_id`-scoped isolation
- Plugin-based extension model (`core/plugins` + `extensions`)
- Tool integration for local computer control and web search

### 3. Repository Layout (Developer-Oriented)

```text
Agent/
├─ gateway/            # runtime orchestration
├─ gateway/http/       # HTTP boundary layer
├─ memory/             # memory write/maintain/recall
├─ core/               # plugin framework
├─ channels/           # channel adapters
├─ computer/           # local capabilities
├─ agentkit/           # MCP + tool-call abstractions
├─ extensions/         # plugin implementations
├─ UI/                 # web frontend
├─ config/             # default + per-user config
├─ tests/              # test suites
└─ start_gateway_service.py
```

### 4. End-to-End Request Flow

Example: one message sent from Web UI:

1. UI calls `/api/chat`
2. HTTP middleware resolves user context
3. Conversation core loads user config and calls LLM
4. Response is persisted into session storage
5. Memory pipeline processes candidate messages asynchronously
6. Future turns may trigger recall from user-wide memory

### 5. Quick Start

```powershell
pip install -r requirements.txt
python start_gateway_service.py
```

Endpoints:
- API: `http://127.0.0.1:8000`
- UI: `http://127.0.0.1:8000/UI/index.html`

### 6. Usage Notes

- Memory is user-wide across sessions (not session-only)
- On upstream 429/rate-limit errors, return readable user-facing messages
- Use a single config update path (`POST /api/config/update`) to avoid duplicate writes

### 7. Engineering Notes

- Keep clean boundaries: Route -> Service -> Storage
- Centralize config updates in `ConfigService`
- Run memory regressions after recall/forgetting changes
- Validate both SSE streaming and JSON fallback when touching frontend streaming logic

### 8. Module Docs

- `gateway/README.md`
- `gateway/http/README.md`
- `memory/README.md`
- `core/README.md`
- `channels/README.md`
- `computer/README.md`
- `agentkit/README.md`
- `extensions/README.md`
- `UI/README.md`
- `config/README.md`
- `tests/README.md`
