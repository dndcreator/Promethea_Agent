from channels.qq_channel import QQChannel
from channels.settings import load_settings


def register(api):
    settings = load_settings({"qq": api.config.get("channel_config") or {}})
    api.register_channel("qq", QQChannel(settings.qq))
