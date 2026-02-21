# Promethea Agent

Promethea Agent 是一个本地优先的多模块 AI 助手系统，包含：
- 对话与工具调用
- Neo4j 图记忆（热/温/冷层）
- 网关事件总线
- 多用户配置与会话隔离
- Web UI 与 Gateway 接口

## 项目结构

```text
Agent/
├─ gateway/         # 网关、事件总线、会话编排、HTTP/WS 入口
├─ memory/          # 图记忆系统
├─ core/            # 插件与核心服务注册
├─ channels/        # 多渠道适配层
├─ computer/        # 本机能力控制（浏览器/文件/进程）
├─ config/          # 默认配置与用户配置
├─ tests/           # 测试
├─ UI/              # 前端页面
└─ start_gateway_service.py
```

## 你需要先知道的三件事

1. 敏感配置（API Key）目前走全局 `.env`，所有用户共享。
2. 非敏感配置走“默认配置 + 用户配置”合并。
3. 会话、记忆、日志都按用户隔离。

## 快速开始

请先看 `QUICK_START.md`（手把手步骤，适合第一次部署）。

## 依赖基线（2026-02-21）

- Python: `>=3.10`（以 `pyproject.toml` 为准）
- 后端运行依赖：`requirements.txt`（与 `pyproject.toml` 同步）
- 开发测试依赖：`pip install -e .[dev]`
- 桌面端构建依赖：Node.js + `@tauri-apps/cli`（见 `package.json`）

说明：
- 依赖的单一事实源是 `pyproject.toml`。
- `requirements.txt` 用于快速部署与兼容旧流程。

## 运行方式

### 1) 安装依赖

```powershell
pip install -r requirements.txt
```

或：

```powershell
pip install -e .
```

如果你要跑测试/格式化等开发流程：

```powershell
pip install -e .[dev]
```

如果你要打包或调试 Tauri 桌面端：

```powershell
npm install
```

### 2) 配置 `.env`

至少配置：
- `API__API_KEY`
- `API__BASE_URL`
- `API__MODEL`

如果启用记忆，还要配置：
- `MEMORY__ENABLED=true`
- `MEMORY__NEO4J__ENABLED=true`
- `MEMORY__NEO4J__URI`
- `MEMORY__NEO4J__USERNAME`
- `MEMORY__NEO4J__PASSWORD`
- `MEMORY__NEO4J__DATABASE`

### 3) 启动服务

```powershell
python start_gateway_service.py
```

默认地址：
- API: `http://127.0.0.1:8000`
- UI: `http://127.0.0.1:8000/UI/index.html`

## 用户隔离说明（当前实现）

- 对话会话：按 `user_id + session_id` 隔离。
- 记忆图：写入与查询都绑定用户上下文；同名 session 不串数据。
- 日志：按用户目录写入，例如 `logs/<user_id>/2026-02-18.log`。

## 主要文档

- `QUICK_START.md`：首次部署与验证
- `gateway/README.md`：网关与事件流
- `memory/README.md`：图记忆模型与运维
- `config/README.md`：配置来源与优先级
- `tests/README.md`：测试执行方式

## 常见问题

### 1) 登录成功但无法对话

通常是 `.env` 没配置 `API__API_KEY`。

### 2) 记忆接口返回不可用

检查 `MEMORY__ENABLED`、Neo4j 连接参数、Neo4j 服务状态。

### 3) 两个用户看到彼此数据

这在当前版本不应发生。先检查你是否复用了同一个登录 token 或同一个 user_id。

## 版本建议

- Python 3.10+
- Neo4j 5.x
- Windows 本地部署优先（当前项目默认脚本面向 Windows/PowerShell）
