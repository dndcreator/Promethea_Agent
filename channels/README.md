# Channels 模块使用说明

`channels` 提供多渠道消息接入抽象层（Web、企业 IM 等）。

## 模块职责

- 屏蔽不同渠道 SDK 差异
- 统一消息格式
- 将消息送入 Gateway 事件流

## 关键概念

- `BaseChannel`：渠道基类
- `ChannelRegistry`：渠道注册管理
- `MessageRouter`：按渠道分发

## 标准消息结构

- `channel`
- `sender`
- `content`
- `message_type`
- `timestamp`

## 新增渠道步骤

1. 继承 `BaseChannel`
2. 实现发送/接收方法
3. 注册到 `ChannelRegistry`
4. 在配置中启用

## 建议

- 渠道层只做适配，不放业务判断
- 鉴权与用户映射统一放在上层（API/Gateway）
