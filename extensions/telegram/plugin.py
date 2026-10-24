from channels.telegram_channel import TelegramChannel
from channels.settings import load_settings


def register(api):
    settings = load_settings({"telegram": api.config.get("channel_config") or {}})
    api.register_channel("telegram", TelegramChannel(settings.telegram))
