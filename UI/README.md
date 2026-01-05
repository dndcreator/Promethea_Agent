# UI界面说明

终端风格的对话界面，支持会话管理、记忆可视化和在线配置。

## 功能模块

### 对话区域
- 流式输出显示
- 多轮对话历史
- 置信度标记（点击可追问）
- 打字机效果

### 侧边栏
- 会话列表
- 快速切换会话
- 新建会话

### 工具栏
- 📊 性能统计：查看token消耗、调用次数等
- 🧠 记忆图谱：可视化三层记忆结构
- ⚙️ 系统设置：在线修改配置

## API接口

### 对话相关
- `POST /api/chat` - 发送消息
- `GET /api/sessions` - 获取会话列表
- `GET /api/sessions/{id}` - 获取会话详情
- `POST /api/followup` - 追问不确定的回答

### 记忆相关
- `GET /api/memory/graph/{session_id}` - 获取记忆图谱
- `POST /api/memory/cluster/{session_id}` - 手动触发温层聚类
- `POST /api/memory/summarize/{session_id}` - 手动生成摘要

### 配置相关
- `GET /api/config` - 获取当前配置
- `POST /api/config` - 更新配置（热重载）
- `GET /api/metrics` - 获取性能统计

## 文件结构
```
UI/
├── index.html      # 页面结构
├── style.css       # 样式（终端风格）
├── script.js       # 核心逻辑
└── README.md       # 本文档
```

## 本地开发

直接用浏览器打开 `index.html` 即可，会自动连接到 `http://127.0.0.1:8000`。

如果后端端口不是8000，修改 `script.js` 中的 `apiBaseUrl`。

## 注意事项

- 记忆图谱需要Neo4j支持
- 置信度检测需要模型支持logprobs
- 配置修改会立即生效，无需重启
