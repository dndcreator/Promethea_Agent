# 快速开始

## 1. 安装依赖
```bash
pip install -r api_server/requirements.txt
```

## 2. 配置API

编辑 `config.json`，填入你的API密钥：
```json
{
  "api": {
    "api_key": "your-api-key-here",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-3.5-turbo"
  }
}
```

支持OpenAI、OpenRouter等兼容接口。

## 3. 启动服务

```bash
python run_api.py
```

浏览器访问 http://localhost:8000 开始对话。

## 4. 可选配置

### 启用记忆系统

需要先安装Neo4j（https://neo4j.com/download/），然后修改配置：
```json
{
  "memory": {
    "enabled": true,
    "neo4j": {
      "enabled": true,
      "uri": "bolt://127.0.0.1:7687",
      "username": "neo4j",
      "password": "your-password"
    }
  }
}
```

### 桌面版打包

```bash
npm install          # 首次运行
npm run build        # 打包成exe
```

打包前需要安装Rust：https://rustup.rs/

---

完成！开始和Promethea对话吧。
