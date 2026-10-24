from channels.dingtalk_channel import DingTalkChannel
from channels.settings import load_settings


def register(api):
    settings = load_settings({"dingtalk": api.config.get("channel_config") or {}})
    channel = DingTalkChannel(settings.dingtalk)
    api.register_channel("dingtalk", channel)

