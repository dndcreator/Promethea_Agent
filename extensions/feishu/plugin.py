from channels.feishu_channel import FeishuChannel
from channels.settings import load_settings


def register(api):
    settings = load_settings({"feishu": api.config.get("channel_config") or {}})
    channel = FeishuChannel(settings.feishu)
    api.register_channel("feishu", channel)

