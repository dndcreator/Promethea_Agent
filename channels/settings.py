"""Operator-owned channel settings; credentials never enter per-user model config."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GroupBinding(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)
    allowed_senders: list[str] = Field(min_length=1, max_length=100)


class BotSettings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    enabled: bool = False
    groups: dict[str, GroupBinding] = Field(default_factory=dict)
    request_timeout_s: float = Field(default=20, ge=1, le=120)
    reply_chars: int = Field(default=1800, ge=100, le=4000)
    max_reply_parts: int = Field(default=4, ge=1, le=4)


class QQSettings(BotSettings):
    app_id: str = ""
    client_secret: SecretStr = SecretStr("")
    bot_secret: SecretStr = SecretStr("")
    signature_max_age_s: int = Field(default=300, ge=30, le=1800)

    @model_validator(mode="after")
    def validate_enabled(self):
        if self.enabled and (not self.app_id or not self.client_secret.get_secret_value() or not self.bot_secret.get_secret_value()):
            raise ValueError("QQ requires app_id, client_secret and bot_secret")
        return self


class TelegramSettings(BotSettings):
    bot_token: SecretStr = SecretStr("")
    webhook_secret: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def validate_enabled(self):
        if self.enabled and (not self.bot_token.get_secret_value() or not self.webhook_secret.get_secret_value()):
            raise ValueError("Telegram requires bot_token and webhook_secret")
        return self


class FeishuSettings(BotSettings):
    app_id: str = ""
    app_secret: SecretStr = SecretStr("")
    verification_token: SecretStr = SecretStr("")
    encrypt_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def validate_enabled(self):
        if self.enabled and not all((self.app_id, self.app_secret.get_secret_value(), self.verification_token.get_secret_value(), self.encrypt_key.get_secret_value())):
            raise ValueError("Feishu requires app_id, app_secret, verification_token and encrypt_key")
        return self


class DingTalkSettings(BotSettings):
    app_key: str = ""
    app_secret: SecretStr = SecretStr("")
    robot_code: str = ""
    corp_id: str = ""

    @model_validator(mode="after")
    def validate_enabled(self):
        if self.enabled and not all((self.app_key, self.app_secret.get_secret_value(), self.robot_code, self.corp_id)):
            raise ValueError("DingTalk requires app_key, app_secret, robot_code and corp_id")
        return self


class WeComSettings(BotSettings):
    corp_id: str = ""
    agent_id: int = Field(default=0, ge=0)
    app_secret: SecretStr = SecretStr("")
    callback_token: SecretStr = SecretStr("")
    encoding_aes_key: SecretStr = SecretStr("")
    reply_chars: int = Field(default=500, ge=100, le=500)

    @model_validator(mode="after")
    def validate_enabled(self):
        if self.enabled:
            import base64
            if not all((self.corp_id, self.agent_id, self.app_secret.get_secret_value(), self.callback_token.get_secret_value())):
                raise ValueError("WeCom requires corp_id, agent_id, app_secret and callback_token")
            key = self.encoding_aes_key.get_secret_value()
            if len(key) != 43 or len(base64.b64decode(key + "=", validate=True)) != 32:
                raise ValueError("WeCom encoding_aes_key must encode a 32-byte key")
            if self.groups:
                raise ValueError("WeCom application callbacks support private text only")
        return self


class ChannelSettings(BaseSettings):
    qq: QQSettings = Field(default_factory=QQSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    feishu: FeishuSettings = Field(default_factory=FeishuSettings)
    dingtalk: DingTalkSettings = Field(default_factory=DingTalkSettings)
    wecom: WeComSettings = Field(default_factory=WeComSettings)
    queue_limit: int = Field(default=200, ge=1, le=10000)
    turn_timeout_s: float = Field(default=240, ge=10, le=3600)
    retention_days: int = Field(default=30, ge=1, le=365)
    workers: Literal[1] = 1  # One ordered ingress worker per Runtime, not distributed delivery.

    model_config = SettingsConfigDict(env_prefix="CHANNELS__", env_nested_delimiter="__", env_file=str(Path(__file__).resolve().parents[1] / ".env"), extra="ignore", hide_input_in_errors=True)

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return env_settings, dotenv_settings, init_settings, file_secret_settings


def load_settings(values=None):
    values = values or {}
    return ChannelSettings(**{name: value for name, value in values.items() if name in ChannelSettings.model_fields})
