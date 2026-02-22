# Channels Module

---

## 中文文档

### 1. 模块职责

`channels` 负责对接不同消息来源，并统一成系统可处理的消息格式。

### 2. 关键文件

- `channels/base.py`：渠道基类定义
- `channels/registry.py`：渠道注册中心
- `channels/router.py`：消息路由逻辑
- `channels/web_channel.py`：Web 渠道
- `channels/wecom_channel.py`：企业微信渠道
- `channels/feishu_channel.py`：飞书渠道
- `channels/dingtalk_channel.py`：钉钉渠道

### 3. 工作流

1. 渠道接收消息
2. 转换为统一结构
3. 交给 gateway/对话核心处理
4. 将回复写回对应渠道

### 4. 使用注意事项

- 渠道层只做适配，不做复杂业务判断
- 用户映射和权限判断尽量由上层统一处理
- 新渠道先保证收发闭环，再逐步加高级能力

---

## English Documentation

### 1. Purpose

`channels` integrates different message sources and normalizes them into a unified internal format.

### 2. Key Files

- `channels/base.py`: base channel abstraction
- `channels/registry.py`: channel registry
- `channels/router.py`: message routing
- `channels/web_channel.py`: web channel
- `channels/wecom_channel.py`: WeCom channel
- `channels/feishu_channel.py`: Feishu channel
- `channels/dingtalk_channel.py`: DingTalk channel

### 3. Workflow

1. Channel receives inbound message
2. Normalizes payload shape
3. Delegates to gateway/conversation processing
4. Sends response back via the same channel

### 4. Notes

- keep channel layer as adapter-only
- centralize auth/user mapping in upper layers
- get basic send/receive stable before adding advanced features
