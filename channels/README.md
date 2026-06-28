# Channels Module

`channels` integrates different message sources and normalizes them into a unified internal format.

## Key Files

- `channels/base.py`: base channel abstraction
- `channels/registry.py`: channel registry
- `channels/router.py`: message routing
- `channels/web_channel.py`: web channel
- `channels/wecom_channel.py`: WeCom channel
- `channels/feishu_channel.py`: Feishu channel
- `channels/dingtalk_channel.py`: DingTalk channel

## Workflow

1. Channel receives inbound message.
2. It normalizes payload shape.
3. It delegates to gateway/conversation processing.
4. It sends the response back through the same channel.

## Notes

- Keep the channel layer adapter-only.
- Centralize auth and user mapping in upper layers.
- Get basic send/receive stable before adding advanced features.
