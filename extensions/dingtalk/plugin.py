from channels.dingtalk_channel import DingTalkChannel
from channels.base import ChannelConfig


def register(api):
    channel_cfg = api.config.get("channel_config") or {}
    channel = DingTalkChannel(ChannelConfig(**channel_cfg))
    api.register_channel("dingtalk", channel)

