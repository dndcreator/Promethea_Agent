from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.json"
LEGACY_CONFIG_PATH = PROJECT_ROOT / "config.json"


class SystemConfig(BaseSettings):
    version: str = Field(default="1.0")
    base_dir: Path = Field(default_factory=lambda: PROJECT_ROOT)
    log_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "logs")
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
    base_url: str = Field(default="")
    model: str = Field(default="")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=1, le=8192)
    max_history_rounds: int = Field(default=10, ge=1, le=100)
    timeout: Optional[int] = Field(default=None, ge=1, le=300)
    retry_count: Optional[int] = Field(default=None, ge=0, le=10)
    failover_models: list[str] = Field(default_factory=list)
    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if v and v != "placeholder-key-not-set":
            v.encode("ascii")
        return v

    @field_validator("failover_models", mode="before")
    @classmethod
    def normalize_failover_models(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        if isinstance(v, str):
            raw = v.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [part.strip() for part in raw.split(",") if part.strip()]
        return []


class Neo4jConfig(BaseSettings):
    enabled: bool = Field(default=True)
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
    summary_model: str = Field(default="")
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


class MemoryMigrationConfig(BaseSettings):
    mode: str = Field(default="off")
    source_backend: str = Field(default="")
    target_backend: str = Field(default="")
    checkpoint: str = Field(default="")

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        value = (v or "off").strip().lower()
        if value not in {"off", "dual_write", "cutover"}:
            raise ValueError("memory.migration.mode must be one of: off, dual_write, cutover")
        return value


class MemoryRawLogConfig(BaseSettings):
    enabled: bool = Field(default=True)
    path: str = Field(default="memory/raw_log.jsonl")
    state_path: str = Field(default="memory/raw_log.state.json")
    defer_hot_write: bool = Field(default=True)
    flush_interval_s: float = Field(default=5.0, ge=0.2)
    max_batch_size: int = Field(default=32, ge=1, le=2048)


class HippocampusConfig(BaseSettings):
    enabled: bool = Field(default=True)
    cluster_every_messages: int = Field(default=12, ge=1)
    cluster_min_interval_s: int = Field(default=300, ge=0)
    idle_cluster_delay_s: int = Field(default=120, ge=10)
    idle_cluster_min_messages: int = Field(default=2, ge=1)
    idle_cluster_min_interval_s: int = Field(default=60, ge=0)
    summary_min_interval_s: int = Field(default=600, ge=0)
    decay_interval_s: int = Field(default=24 * 3600, ge=60)


class MemoryConfig(BaseSettings):
    enabled: bool = Field(default=True)
    profile: str = Field(default="balanced")
    store_backend: str = Field(default="neo4j")
    sqlite_graph_path: str = Field(default="memory/sqlite_graph.db")
    flat_memory_path: str = Field(default="memory/flat_memory.jsonl")
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    api: MemoryAPIConfig = Field(default_factory=MemoryAPIConfig)
    hot_layer: HotLayerConfig = Field(default_factory=HotLayerConfig)
    warm_layer: WarmLayerConfig = Field(default_factory=WarmLayerConfig)
    cold_layer: ColdLayerConfig = Field(default_factory=ColdLayerConfig)
    gating: MemoryGatingConfig = Field(default_factory=MemoryGatingConfig)
    migration: MemoryMigrationConfig = Field(default_factory=MemoryMigrationConfig)
    raw_log: MemoryRawLogConfig = Field(default_factory=MemoryRawLogConfig)
    hippocampus: HippocampusConfig = Field(default_factory=HippocampusConfig)

    @field_validator("store_backend")
    @classmethod
    def validate_store_backend(cls, v: str) -> str:
        value = (v or "neo4j").strip().lower()
        if value not in {"neo4j", "sqlite_graph", "flat_memory"}:
            raise ValueError("memory.store_backend must be one of: neo4j, sqlite_graph, flat_memory")
        return value

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, v: str) -> str:
        value = (v or "balanced").strip().lower()
        if value not in {"conservative", "balanced", "aggressive"}:
            raise ValueError("memory.profile must be one of: conservative, balanced, aggressive")
        return value


class ReasoningConfig(BaseSettings):
    enabled: bool = Field(default=True)
    mode: str = Field(default="react_tot")
    max_depth: int = Field(default=4, ge=1, le=12)
    max_nodes: int = Field(default=24, ge=4, le=256)
    max_iterations: int = Field(default=16, ge=1, le=256)
    max_memory_calls: int = Field(default=6, ge=0, le=64)
    max_tool_calls: int = Field(default=8, ge=0, le=64)
    max_replan_rounds: int = Field(default=6, ge=0, le=32)
    max_react_rounds_total: int = Field(default=14, ge=1, le=256)
    target_runtime_seconds: float = Field(default=240.0, ge=30.0, le=3600.0)
    max_runtime_seconds: float = Field(default=480.0, ge=60.0, le=7200.0)
    max_low_yield_tool_failures: int = Field(default=4, ge=0, le=64)
    plan_max_steps: int = Field(default=8, ge=1, le=32)
    beam_width: int = Field(default=3, ge=1, le=16)
    branch_factor: int = Field(default=3, ge=1, le=16)
    candidate_votes: int = Field(default=3, ge=1, le=9)
    min_branch_score: float = Field(default=0.0, ge=0.0, le=1.0)
    moirai_export_plan: bool = Field(default=False)
    moirai_auto_start: bool = Field(default=True)
    workflow_tool_bridge: bool = Field(default=True)
    debug_log: bool = Field(default=False)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in {"react_tot"}:
            raise ValueError("reasoning.mode must be 'react_tot'")
        return value


class OrgBrainConfig(BaseSettings):
    enabled: bool = Field(default=False)
    org_id: str = Field(default="")
    recall_priority: str = Field(default="blend")
    confirmation_queue: bool = Field(default=True)
    audience_default: str = Field(default="业务部门")
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    allowed_suffixes: list[str] = Field(
        default_factory=lambda: [".txt", ".md", ".markdown", ".csv", ".json", ".docx", ".pdf"]
    )
    recall_top_k_default: int = Field(default=5, ge=1, le=50)
    recall_context_type_default: str = Field(default="writing")
    chat_top_k: int = Field(default=5, ge=1, le=50)
    chat_context_type: str = Field(default="chat")
    summary_label: str = Field(default="Organization context hints")
    summary_max_items: int = Field(default=8, ge=1, le=50)
    extract_text_max_chars: int = Field(default=5000, ge=500, le=200000)
    heuristic_max_lines: int = Field(default=30, ge=1, le=1000)
    heuristic_max_items: int = Field(default=15, ge=1, le=200)

    @field_validator("recall_priority")
    @classmethod
    def validate_recall_priority(cls, v: str) -> str:
        value = (v or "blend").strip().lower()
        if value not in {"blend", "override_persona"}:
            raise ValueError("org_brain.recall_priority must be one of: blend, override_persona")
        return value

    @field_validator("allowed_suffixes", mode="before")
    @classmethod
    def normalize_allowed_suffixes(cls, v: Any) -> list[str]:
        if v is None:
            return [".txt", ".md", ".markdown", ".csv", ".json", ".docx", ".pdf"]
        if isinstance(v, str):
            raw = v.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        v = parsed
                except Exception:
                    v = [part.strip() for part in raw.split(",") if part.strip()]
            else:
                v = [part.strip() for part in raw.split(",") if part.strip()]
        if not isinstance(v, list):
            return [".txt", ".md", ".markdown", ".csv", ".json", ".docx", ".pdf"]
        out: list[str] = []
        for item in v:
            s = str(item or "").strip().lower()
            if not s:
                continue
            if not s.startswith("."):
                s = "." + s
            out.append(s)
        return sorted(list(dict.fromkeys(out)))



class SandboxConfig(BaseSettings):
    enabled: bool = Field(default=False)
    profile: str = Field(default="off")
    workspace_access: str = Field(default="rw")  # rw|ro|none
    command_mode: str = Field(default="allowlist")  # allowlist|audit
    allowed_commands: list[str] = Field(default_factory=lambda: [
        "python",
        "pytest",
        "pip",
        "uv",
        "git",
        "rg",
        "cmd",
        "powershell",
    ])
    deny_fragments: list[str] = Field(default_factory=lambda: [
        "rm -rf",
        "del /f /q",
        "format ",
        "shutdown",
        "reboot",
        "mkfs",
        "diskpart",
        "net user",
        "reg add",
    ])
    network_mode: str = Field(default="restricted")  # restricted|none
    allowed_domains: list[str] = Field(default_factory=list)
    block_private_network: bool = Field(default=True)

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, v: str) -> str:
        value = (v or "off").strip().lower()
        if value not in {"off", "dev", "strict"}:
            raise ValueError("sandbox.profile must be one of: off, dev, strict")
        return value

    @field_validator("workspace_access")
    @classmethod
    def validate_workspace_access(cls, v: str) -> str:
        value = (v or "rw").strip().lower()
        if value not in {"rw", "ro", "none"}:
            raise ValueError("sandbox.workspace_access must be one of: rw, ro, none")
        return value

    @field_validator("command_mode")
    @classmethod
    def validate_command_mode(cls, v: str) -> str:
        value = (v or "allowlist").strip().lower()
        if value not in {"allowlist", "audit"}:
            raise ValueError("sandbox.command_mode must be one of: allowlist, audit")
        return value

    @field_validator("network_mode")
    @classmethod
    def validate_network_mode(cls, v: str) -> str:
        value = (v or "restricted").strip().lower()
        if value not in {"restricted", "none"}:
            raise ValueError("sandbox.network_mode must be one of: restricted, none")
        return value
class SystemPrompts(BaseSettings):
    Promethea_system_prompt: str = Field(
        default=(
            "You are Promethea, a cognitive agent runtime assistant. "
            "When asked who you are, answer as Promethea and do not identify as the underlying model, provider, API vendor, or hosting service. "
            "Promethea is a runtime with conversation, graph/layered long-term memory, reasoning, tools, skills, workflows, files, automation, and optional organization-brain context when those capabilities are available. "
            "Use recalled memory naturally when it is provided; do not claim that cross-conversation memory is impossible as a fixed limitation. "
            "If no relevant memory is available in the current prompt, say that you do not have enough recalled context yet. "
            "When reasoning context is provided, synthesize from it and produce a useful final answer rather than discarding the reasoning work. "
            "For technical or product tasks, be precise, structured, explicit about assumptions, and action-oriented. "
            "For normal conversation, remain concise and human-readable. "
            "Never let style guidance override policy, safety, tool constraints, memory boundaries, or the user's explicit request."
        )
    )


class PrometheaConfig(BaseSettings):
    config_version: str = Field(default="1")
    system: SystemConfig = Field(default_factory=SystemConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    prompts: SystemPrompts = Field(default_factory=SystemPrompts)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)
    org_brain: OrgBrainConfig = Field(default_factory=OrgBrainConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
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


def _set_nested_value(target: dict, path: tuple[str, ...], value: Any) -> None:
    current = target
    for segment in path[:-1]:
        current = current.setdefault(segment, {})
    current[path[-1]] = value


def _resolve_key_case_insensitive(payload: dict, key: str) -> Optional[str]:
    if key in payload:
        return key
    key_lower = key.lower()
    for existing in payload.keys():
        if str(existing).lower() == key_lower:
            return str(existing)
    return None


def _get_nested_value_ci(payload: dict, path: tuple[str, ...]) -> tuple[bool, Any]:
    current: Any = payload
    for segment in path:
        if not isinstance(current, dict):
            return False, None
        resolved = _resolve_key_case_insensitive(current, segment)
        if resolved is None:
            return False, None
        current = current.get(resolved)
    return True, current


def _set_nested_value_ci(payload: dict, path: tuple[str, ...], value: Any) -> bool:
    current: Any = payload
    for segment in path[:-1]:
        if not isinstance(current, dict):
            return False
        resolved = _resolve_key_case_insensitive(current, segment)
        if resolved is None:
            return False
        current = current.get(resolved)
    if not isinstance(current, dict):
        return False
    last = _resolve_key_case_insensitive(current, path[-1])
    if last is None:
        return False
    current[last] = value
    return True


def _overlay_explicit_env_values(merged_data: dict, base_from_env: PrometheaConfig) -> None:
    env_data = base_from_env.model_dump()
    explicit_env_keys = set(os.environ.keys())
    env_file = dotenv_values(str(ENV_FILE)) if ENV_FILE.exists() else {}
    explicit_env_keys.update(str(k) for k in env_file.keys() if k)
    for env_name in sorted(explicit_env_keys):
        if "__" not in env_name:
            continue
        path = tuple(seg for seg in str(env_name).split("__") if seg)
        if not path:
            continue
        found, value = _get_nested_value_ci(env_data, path)
        if not found:
            continue
        _set_nested_value_ci(merged_data, path, value)


def load_config() -> PrometheaConfig:
    base_from_env = PrometheaConfig()
    merged_data = base_from_env.model_dump()

    config_path = DEFAULT_CONFIG_PATH
    if not config_path.exists():
        legacy_path = LEGACY_CONFIG_PATH
        config_path = legacy_path if legacy_path.exists() else None

    if config_path and config_path.exists():
        try:
            # Accept UTF-8 BOM files produced by some editors/exporters.
            with config_path.open("r", encoding="utf-8-sig") as f:
                file_data = json.load(f)
            _deep_merge(merged_data, file_data)
        except Exception as e:
            print(f"Warning: failed to load {config_path}: {e}")

    # .env values should always win when explicitly provided; default.json only fills gaps.
    _overlay_explicit_env_values(merged_data, base_from_env)

    cfg = PrometheaConfig(**merged_data)

    if not cfg.api.api_key or cfg.api.api_key == "placeholder-key-not-set":
        print("Warning: API key is not configured")
        print("Set API__API_KEY in .env before running chat")

    return cfg


config = load_config()
AI_NAME = "Promethea"









