# Channels 模块

Channels 模块提供多平台消息通道抽象，支持钉钉、飞书、企微、Web 等多种渠道。

## 架构设计

```
┌─────────────────────────────────────┐
│      MessageRouter (消息路由)       │
│  根据通道类型路由到对应的 Channel    │
└─────────────────────────────────────┘
              │
    ┌─────────┼─────────┬─────────┐
    ▼         ▼         ▼         ▼
DingTalk  Feishu    WeCom    Web
Channel   Channel   Channel  Channel
```

## 核心组件

### 1. BaseChannel (`base.py`)

- **职责**: 所有通道的基类
- **接口**:
  - `send_message()` - 发送消息
  - `receive_message()` - 接收消息
  - `get_channel_type()` - 获取通道类型

### 2. ChannelRegistry (`registry.py`)

- **职责**: 通道注册表
- **功能**:
  - 注册和查找通道
  - 管理通道生命周期

### 3. MessageRouter (`router.py`)

- **职责**: 消息路由
- **功能**:
  - 根据通道类型路由消息
  - 消息格式转换

## 支持的通道

### 1. Web Channel (`web_channel.py`)

- **类型**: Web 网页端
- **特点**: 
  - 通过 WebSocket 或 HTTP 轮询
  - 支持实时双向通信

### 2. DingTalk Channel (`dingtalk_channel.py`)

- **类型**: 钉钉
- **特点**:
  - 企业应用集成
  - 支持群聊和私聊

### 3. Feishu Channel (`feishu_channel.py`)

- **类型**: 飞书
- **特点**:
  - 企业应用集成
  - 支持群聊和私聊

### 4. WeCom Channel (`wecom_channel.py`)

- **类型**: 企业微信
- **特点**:
  - 企业应用集成
  - 支持群聊和私聊

## 消息格式

### Message 结构

```python
class Message:
    channel: str          # 通道类型
    sender: str          # 发送者ID
    content: str         # 消息内容
    message_type: str    # 消息类型 (text/image/file)
    timestamp: datetime  # 时间戳
```

## 使用示例

### 注册通道

```python
from channels import ChannelRegistry, BaseChannel

registry = ChannelRegistry()

class MyChannel(BaseChannel):
    def send_message(self, message):
        # 实现发送逻辑
        pass

registry.register("my_channel", MyChannel())
```

### 路由消息

```python
from channels import MessageRouter

router = MessageRouter(registry)
router.route_message(message)
```

## 通道配置

通道配置在 `gateway_config.json` 中：

```json
{
  "channels": {
    "web": {
      "enabled": true,
      "port": 8000
    },
    "dingtalk": {
      "enabled": false,
      "app_key": "...",
      "app_secret": "..."
    }
  }
}
```

## 扩展新通道

1. 继承 `BaseChannel`
2. 实现 `send_message()` 和 `receive_message()`
3. 在 `registry.py` 中注册

```python
from channels.base import BaseChannel

class CustomChannel(BaseChannel):
    def send_message(self, message):
        # 实现发送逻辑
        pass
    
    def receive_message(self):
        # 实现接收逻辑
        pass
```

## 相关文档

- [主 README](../README.md)
- [Gateway 模块](../gateway/README.md)
