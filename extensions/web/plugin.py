from channels.web_channel import WebChannel
from channels.base import ChannelConfig


def register(api):
    """
    Promethea plugin entrypoint (Moltbot-style).
    """
    channel_cfg = api.config.get("channel_config") or {}
    channel = WebChannel(ChannelConfig(**channel_cfg))
    api.register_channel("web", channel)

