from channels.wecom_channel import WeComChannel
from channels.base import ChannelConfig


def register(api):
    channel_cfg = api.config.get("channel_config") or {}
    channel = WeComChannel(ChannelConfig(**channel_cfg))
    api.register_channel("wecom", channel)

