from channels.wecom_channel import WeComChannel
from channels.settings import load_settings


def register(api):
    settings = load_settings({"wecom": api.config.get("channel_config") or {}})
    channel = WeComChannel(settings.wecom)
    api.register_channel("wecom", channel)

