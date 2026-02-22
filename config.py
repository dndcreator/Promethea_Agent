from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SystemConfig(BaseSettings):
    version: str = Field(default="1.0")
    base_dir: Path = Field(default_factory=lambda: Path(__file__).parent)
    log_dir: Path = Field(default_factory=lambda: Path(__file__).parent / "logs")
    stream_mode: bool = Field(default=True)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    session_ttl_hours: int = Field(default=0, ge=0)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        value = (v or "INFO").upper()
        if value not in valid_levels:
            raise ValueError(f"log_level must be one of: {sorted(valid_levels)}")
        return value


class APIConfig(BaseSettings):
    api_key: str = Field(default="placeholder-key-not-set")
    base_url: str = Field(default="https://openrouter.ai/api/v1")
    model: str = Field(default="nvidia/nemotron-3-nano-30b-a3b:free")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=1, le=8192)
    max_history_rounds: int = Field(default=10, ge=1, le=100)
    timeout: Optional[int] = Field(default=None, ge=1, le=300)
    retry_count: Optional[int] = Field(default=None, ge=0, le=10)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if v and v != "placeholder-key-not-set":
            v.encode("ascii")
        return v


class Neo4jConfig(BaseSettings):
    enabled: bool = Field(default=False)
    uri: str = Field(default="bolt://localhost:7687")
    username: str = Field(default="neo4j")
    password: str = Field(default="password")
    database: str = Field(default="neo4j")
    max_connection_lifetime: int = Field(default=3600)
    max_connection_pool_size: int = Field(default=50)
    connection_timeout: int = Field(default=3)


class HotLayerConfig(BaseSettings):
    max_tuples_per_message: int = Field(default=10)
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    enable_coreference: bool = Field(default=False)
    enable_time_normalization: bool = Field(default=True)
    message_retention_days: int = Field(default=30, ge=1)
    message_cleanup_batch: int = Field(default=200, ge=20)


class WarmLayerConfig(BaseSettings):
    enabled: bool = Field(default=True)
    embedding_model: str = Field(default="text-embedding-ada-002")
    clustering_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    min_cluster_size: int = Field(default=3, ge=1)
    max_concepts: int = Field(default=100, ge=1)
    stabilize_min_sessions: int = Field(default=2, ge=1)
    stabilize_min_mentions: int = Field(default=3, ge=1)
    stabilize_importance_floor: float = Field(default=0.8, ge=0.0, le=1.0)
    cluster_every_messages: int = Field(default=12, ge=1)
    cluster_min_interval_s: int = Field(default=300, ge=0)
    idle_cluster_delay_s: int = Field(default=120, ge=10)
    idle_cluster_min_messages: int = Field(default=2, ge=1)
    idle_cluster_min_interval_s: int = Field(default=60, ge=0)


class ColdLayerConfig(BaseSettings):
    summary_model: str = Field(default="gpt-4")
    max_summary_length: int = Field(default=500, ge=1)
    compression_threshold: int = Field(default=50, ge=1)


class MemoryRecallFilterConfig(BaseSettings):
    enabled: bool = Field(default=True)
    min_query_chars: int = Field(default=6, ge=0)
    max_query_chars: int = Field(default=4000, ge=64)


class MemoryWriteFilterConfig(BaseSettings):
    enabled: bool = Field(default=True)
    min_user_chars: int = Field(default=4, ge=0)
    min_assistant_chars_for_short_user: int = Field(default=20, ge=0)
    max_combined_chars: int = Field(default=8000, ge=256)


class MemoryDedupeConfig(BaseSettings):
    recent_write_cache_size: int = Field(default=2000, ge=100)
    min_candidate_chars: int = Field(default=8, ge=1)


class MemoryGatingConfig(BaseSettings):
    recall_filter: MemoryRecallFilterConfig = Field(default_factory=MemoryRecallFilterConfig)
    write_filter: MemoryWriteFilterConfig = Field(default_factory=MemoryWriteFilterConfig)
    dedupe: MemoryDedupeConfig = Field(default_factory=MemoryDedupeConfig)


class MemoryAPIConfig(BaseSettings):
    use_main_api: bool = Field(default=True)
    api_key: str = Field(default="")
    base_url: str = Field(default="https://openrouter.ai/api/v1")
    model: str = Field(default="")


class MemoryConfig(BaseSettings):
    enabled: bool = Field(default=False)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    api: MemoryAPIConfig = Field(default_factory=MemoryAPIConfig)
    hot_layer: HotLayerConfig = Field(default_factory=HotLayerConfig)
    warm_layer: WarmLayerConfig = Field(default_factory=WarmLayerConfig)
    cold_layer: ColdLayerConfig = Field(default_factory=ColdLayerConfig)
    gating: MemoryGatingConfig = Field(default_factory=MemoryGatingConfig)


class SystemPrompts(BaseSettings):
    Promethea_system_prompt: str = Field(
        default=(
            "You are Promethea, a practical AI assistant. "
            "For technical tasks, be precise and structured. "
            "For normal conversation, remain clear and concise."
        )
    )


class PrometheaConfig(BaseSettings):
    system: SystemConfig = Field(default_factory=SystemConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    prompts: SystemPrompts = Field(default_factory=SystemPrompts)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.system.log_dir.mkdir(exist_ok=True)


def _deep_merge(target: dict, source: dict) -> dict:
    for k, v in source.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_merge(target[k], v)
        else:
            target[k] = v
    return target


def load_config() -> PrometheaConfig:
    base_from_env = PrometheaConfig()
    merged_data = base_from_env.model_dump()

    config_path = Path("config/default.json")
    if not config_path.exists():
        legacy_path = Path("config.json")
        config_path = legacy_path if legacy_path.exists() else None

    if config_path and config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                file_data = json.load(f)
            _deep_merge(merged_data, file_data)
        except Exception as e:
            print(f"Warning: failed to load {config_path}: {e}")

    # Sensitive values stay sourced from env/.env.
    merged_data.setdefault("api", {})["api_key"] = base_from_env.api.api_key
    merged_data.setdefault("memory", {}).setdefault("neo4j", {})["password"] = base_from_env.memory.neo4j.password
    merged_data.setdefault("memory", {}).setdefault("api", {})["api_key"] = base_from_env.memory.api.api_key

    cfg = PrometheaConfig(**merged_data)

    if not cfg.api.api_key or cfg.api.api_key == "placeholder-key-not-set":
        print("Warning: API key is not configured")
        print("Set API__API_KEY in .env before running chat")

    return cfg


config = load_config()
AI_NAME = "Promethea"
