# Promethea Agent (普罗米娅助手)

> **一个可进化、模块化、全能型的 AI 智能助手框架**

Promethea 是一个基于 Python 构建的现代化 Agent 系统。它拥有**“手”**（电脑控制）、**“眼”**（网络搜索）和**“脑”**（长期记忆），并支持多用户个性化配置和全渠道接入。

当前版本已对齐 Moltbot/Clawdbot 的核心思路：**微内核 + 插件化（extensions）+ 运行时注册表（runtime registry）**。核心只负责加载插件与路由，业务能力由插件注册进来。

---

## 🚀 极简启动指南

默认情况下你只需要做两件事：

1.  **（可选）启动 Neo4j 数据库**（启用记忆时才需要）。
2.  **运行启动脚本**。

### 详细步骤

1.  **环境准备（Windows / PowerShell）**
    - 确保已安装 Python 3.10+
    - 安装依赖（两种方式任选其一）：

```powershell
cd D:\产品\Agent
pip install -e .
```

或：

```powershell
cd D:\产品\Agent
pip install -r requirements.txt
```

如果你需要浏览器自动化能力：

```powershell
playwright install
```

2.  **配置密钥（强烈建议）**
    - 把 `env.example` 复制为 `.env`，并填写：
      - `API_KEY`
      - （如启用记忆）`NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD`

3.  **自检插件系统（推荐）**

```powershell
python scripts\self_check_plugins.py
```

4.  **启动服务**

```powershell
python start_gateway_service.py
```

5.  **开始使用**
    服务启动后，浏览器访问：
    👉 `http://127.0.0.1:8000/UI/index.html`

    *   **首次登录**：在网页端点击“注册”，创建你的管理员账号。
    *   **个性化配置**：登录后在“设置”中填入你的 API Key，并绑定通道账号（如钉钉/飞书/企微）。

---

## ✨ 核心能力

| 能力 | 说明 |
| :--- | :--- |
| **🧠 进化记忆** | 基于 Neo4j 的三层记忆系统，记忆随用户 ID 隔离，越用越懂你。 |
| **⚡ 并行思考** | 支持同时执行多项任务（如“一边查资料，一边写文档”）。 |
| **🖥️ 电脑控制** | 安全接管电脑：操作浏览器、文件系统、运行软件。 |
| **🔐 多用户支持** | 每个用户拥有独立的配置（API Key、人设）和记忆空间。 |
| **🌐 全渠道互通** | 网页端配置绑定后，你在 Telegram/微信 发的消息也能触发同样的个性化服务。 |

---

## 🛠️ 维护与扩展

- **日志**: 运行时日志在 `logs/`（已加入 `.gitignore`，不应提交）。
- **配置**:
  - 敏感信息放 `.env`（已加入 `.gitignore`）
  - 默认配置：`config/default.json`（非敏感配置）
  - 用户配置：`config/users/{user_id}.json`（每个用户的个性化配置）
  - 详细说明：参见 [config/README.md](config/README.md)
- **插件化扩展（Moltbot 风格）**:
  - 插件目录：`extensions/<plugin-id>/`
  - 清单：`extensions/<plugin-id>/promethea.plugin.json`
  - 入口：`extensions/<plugin-id>/plugin.py`（实现 `register(api)`）

## 📚 模块文档

项目采用模块化文档结构，每个主要模块都有独立的 README：

- **[Gateway](gateway/README.md)** - 核心运行平台，事件总线，服务管理
- **[Memory](memory/README.md)** - 三层记忆系统（热层/温层/冷层）
- **[API Server](api_server/README.md)** - HTTP REST API 接口
- **[Channels](channels/README.md)** - 多平台消息通道（钉钉/飞书/企微/Web）
- **[Computer](computer/README.md)** - 电脑控制能力（浏览器/文件系统/进程）
- **[Core](core/README.md)** - 核心插件系统和统一服务接口
- **[Config](config/README.md)** - 配置管理系统

**Promethea Agent** - Your Personal Digital Evolution.
