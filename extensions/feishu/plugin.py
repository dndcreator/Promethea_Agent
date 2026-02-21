from channels.feishu_channel import FeishuChannel
from channels.base import ChannelConfig


def register(api):
    channel_cfg = api.config.get("channel_config") or {}
    channel = FeishuChannel(ChannelConfig(**channel_cfg))
    api.register_channel("feishu", channel)

