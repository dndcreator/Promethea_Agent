# Promethea AI Agent

带记忆的智能对话助手，支持三层记忆系统和图谱可视化。

## 快速开始

### 安装依赖
```bash
pip install -r requirements.txt
```

### 启动服务

**Web模式（推荐开发时使用）**
```bash
python run_api.py
# 浏览器访问 http://localhost:8000
```

**桌面版（推荐日常使用）**
```bash
npm install          # 首次运行需要
npm run dev          # 开发模式
npm run build        # 打包成exe
```

---

## 项目结构

```
Agent/
├── api_server/              # 后端服务
│   ├── chat_router.py       # 对话接口和记忆管理
│   ├── message_manager.py   # 会话消息管理
│   └── server.py            # FastAPI服务器
├── memory/                  # 三层记忆系统
│   ├── hot_layer.py         # 热层：实时信息抽取
│   ├── warm_layer.py        # 温层：语义聚类
│   ├── cold_layer.py        # 冷层：长期摘要
│   └── adapter.py           # 记忆适配器
├── utility/                 # 工具模块
│   └── (预留)               # 工具扩展预留
├── agentkit/                # 工具系统
│   ├── mcp/                 # MCP协议实现
│   └── tools/               # 工具集（搜索等）
├── UI/                      # 前端界面
│   ├── index.html
│   ├── script.js            # 对话、可视化、设置
│   └── style.css
├── src-tauri/               # 桌面版
│   └── src/main.rs          # 窗口和托盘管理
├── config.json              # 配置文件
└── run_api.py               # 启动脚本
```

---

## 功能特性

### 对话系统
- 流式输出（SSE）
- 多轮对话历史
- 会话管理
- 选中文本追问（手动触发）

### 记忆系统
- **热层**：实时提取对话中的关键信息
- **温层**：聚类相似概念，形成知识网络
- **冷层**：生成长期摘要，压缩历史记忆
- Neo4j图谱存储
- D3.js可视化展示

### 工具扩展
- 网络搜索（DuckDuckGo）
- MCP协议支持
- 可自定义添加工具

### 界面功能
- 会话列表
- 记忆图谱查看
- 性能统计
- 在线配置修改

---

## 配置说明

编辑 `config.json` 可修改：

**API配置**
- `api_key`: LLM API密钥
- `base_url`: API地址
- `model`: 使用的模型
- `temperature`: 生成温度（0-2）
- `max_tokens`: 最大生成长度

**记忆系统**
- `memory.enabled`: 是否启用记忆
- `memory.neo4j.enabled`: 是否启用Neo4j
- `memory.neo4j.uri`: Neo4j连接地址

注：部分配置支持在UI设置界面直接修改，无需重启服务。

---

## 添加自定义图标

准备一张方形PNG图片（建议512x512），然后：

```bash
# 方式1：使用Tauri官方工具
cargo install tauri-cli
cd src-tauri
cargo tauri icon ../your-logo.png

# 方式2：使用项目脚本
python generate_icon.py your-logo.png
```

---

## 常见问题

**服务启动失败**
- 检查是否在Agent目录下运行
- 确认已安装依赖：`pip install -r requirements.txt`
- 查看终端错误信息

**Neo4j连接失败**
- 默认情况下记忆系统是启用的，需要先安装Neo4j
- 如果不需要记忆功能，在`config.json`中设置`memory.enabled: false`
- Neo4j安装：https://neo4j.com/download/

**Tauri打包失败**
- 需要先安装Rust：https://rustup.rs/
- Windows需要安装WebView2（通常系统自带）

---

## 技术栈

后端：FastAPI, Pydantic, OpenAI SDK  
存储：Neo4j  
前端：原生JS, D3.js  
桌面：Tauri, Rust
