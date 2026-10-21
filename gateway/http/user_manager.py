import json
import os
import uuid
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger
from passlib.context import CryptContext
from passlib.exc import MissingBackendError

from config import load_config
from memory.neo4j_connector import Neo4jConnectionPool
from gateway.http.identity_store import IdentityStore
from gateway.user_secrets import ensure_user_secrets

# Prefer bcrypt, with PBKDF2 fallback when bcrypt backend is unavailable.
pwd_context = CryptContext(
    schemes=["bcrypt", "pbkdf2_sha256"],
    default="bcrypt",
    deprecated="auto",
)


class UserManager:
    def __init__(self):
        cfg = load_config()
        self.users_dir = Path(__file__).resolve().parents[2] / "config" / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.identity_store = IdentityStore(self.users_dir / "identity.sqlite3")
        self._neo4j_config = cfg.memory.neo4j
        self._legacy_neo4j_pending = bool(getattr(self._neo4j_config, "enabled", False))
        self._legacy_retry_after = 0.0
        self.connector = Neo4jConnectionPool.get_connector(self._neo4j_config)
        self._migrate_legacy_identities()

    def can_register(self) -> tuple[bool, str]:
        return (True, "") if self.identity_store is not None else (False, "identity_store_unavailable")

    def _local_users_path(self) -> Path:
        return self.users_dir / "_local_users.json"

    def _load_local_users(self) -> Dict[str, Any]:
        path = self._local_users_path()
        if not path.exists():
            return {"users": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {"users": []}
        except Exception as e:
            logger.error(f"Read local users failed: {e}")
            return {"users": []}

    def _migrate_legacy_identities(self, *, retry_neo4j: bool = False) -> None:
        legacy_users = list(self._load_local_users().get("users") or [])
        if self.connector is None and retry_neo4j:
            neo4j_config = getattr(self, "_neo4j_config", None)
            if neo4j_config is not None:
                self.connector = Neo4jConnectionPool.get_connector(neo4j_config)
        if self.connector is not None:
            try:
                rows = self.connector.query(
                    "MATCH (u:User) WHERE u.username IS NOT NULL AND u.password_hash IS NOT NULL "
                    "RETURN properties(u) AS user"
                )
                legacy_users.extend(
                    row.get("user")
                    for row in rows
                    if isinstance(row, dict) and isinstance(row.get("user"), dict)
                )
                self._legacy_neo4j_pending = False
            except Exception as exc:
                self._legacy_neo4j_pending = True
                logger.warning(f"Legacy Neo4j identity migration skipped: {exc}")
        result = self.identity_store.import_legacy(legacy_users)
        for user in legacy_users:
            if not isinstance(user, dict):
                continue
            user_id = user.get("user_id") or user.get("id")
            if not user_id or self.identity_store.get_by_id(str(user_id)) is None:
                continue
            for key, value in user.items():
                if key.startswith("channel_") and value:
                    try:
                        self.identity_store.bind_channel(
                            str(user_id),
                            key.removeprefix("channel_"),
                            str(value),
                        )
                    except Exception as exc:
                        logger.warning(f"Legacy channel binding migration skipped: {exc}")
        if result["imported"] or result["conflicts"]:
            logger.info(
                "Legacy identity migration: imported={}, existing={}, conflicts={}",
                result["imported"],
                result["existing"],
                result["conflicts"],
            )

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        user = self.identity_store.get_by_username(username)
        now = time.monotonic()
        if (
            user is None
            and bool(getattr(self, "_legacy_neo4j_pending", False))
            and now >= float(getattr(self, "_legacy_retry_after", 0.0))
        ):
            self._legacy_retry_after = now + 5.0
            self._migrate_legacy_identities(retry_neo4j=True)
            user = self.identity_store.get_by_username(username)
        return user

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.identity_store.get_by_id(user_id)

    def create_user(self, username: str, password: str, agent_name: str = "Promethea") -> Optional[str]:
        can_register, reason = self.can_register()
        if not can_register:
            logger.error(f"Cannot create user: {reason}")
            return None

        if self.get_user_by_username(username):
            logger.warning(f"User already exists: {username}")
            return None

        password_hash = self._hash_password(password)
        raw_uuid = str(uuid.uuid4())

        try:
            self.identity_store.create(
                {
                    "id": f"user_{raw_uuid}",
                    "username": username,
                    "password_hash": password_hash,
                    "agent_name": agent_name,
                    "user_id": raw_uuid,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self.create_user_config(raw_uuid, agent_name)
            logger.info(f"User created: user_{raw_uuid}")
            return raw_uuid
        except Exception as e:
            logger.error(f"Create user failed: {e}")
            return None

    @staticmethod
    def _hash_password(password: str) -> str:
        try:
            return pwd_context.hash(password)
        except (MissingBackendError, ValueError):
            # Fallback when bcrypt backend is missing or runtime-incompatible.
            fallback_ctx = CryptContext(
                schemes=["pbkdf2_sha256"],
                default="pbkdf2_sha256",
                deprecated="auto",
            )
            return fallback_ctx.hash(password)

    def create_user_config(self, user_uuid: str, agent_name: str):
        user_dir = self.users_dir / user_uuid
        user_dir.mkdir(parents=True, exist_ok=True)
        config_path = user_dir / "config.json"

        default_config = self._build_user_default_config(agent_name)

        try:
            self._write_json_atomic(config_path, default_config)
            # Create a user-scoped sensitive config copy only when absent.
            # Existing user env files are never overwritten.
            ensure_user_secrets(user_uuid)
        except Exception as e:
            logger.error(f"Create user config failed: {e}")

    @staticmethod
    def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
        """
        Atomically write JSON to disk to avoid truncated/corrupted files
        when process interruption happens during write.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_file = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_file)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            raise

    @staticmethod
    def _build_user_default_config(agent_name: str) -> Dict[str, Any]:
        """
        Build first-user config from system default template while keeping
        env-only secrets out of persisted user config files.
        """
        try:
            cfg = load_config().model_dump(mode="json")
        except Exception:
            cfg = {}

        if not isinstance(cfg, dict):
            cfg = {}

        cfg["agent_name"] = agent_name
        cfg.setdefault("system_prompt", "")

        # Never persist deployment-specific model routing or secrets in
        # per-user config files. Users inherit runtime provider settings from
        # env/default config unless they are explicitly supported as user scope.
        if isinstance(cfg.get("api"), dict):
            api_cfg = dict(cfg.get("api") or {})
            api_cfg.pop("api_key", None)
            api_cfg.pop("base_url", None)
            api_cfg.pop("model", None)
            api_cfg.pop("failover_models", None)
            cfg["api"] = api_cfg
        if isinstance(cfg.get("memory"), dict):
            mem_cfg = dict(cfg.get("memory") or {})
            if isinstance(mem_cfg.get("api"), dict):
                mem_api = dict(mem_cfg.get("api") or {})
                mem_api.pop("api_key", None)
                mem_api.pop("base_url", None)
                mem_api.pop("model", None)
                mem_cfg["api"] = mem_api
            if isinstance(mem_cfg.get("neo4j"), dict):
                neo_cfg = dict(mem_cfg.get("neo4j") or {})
                neo_cfg.pop("password", None)
                mem_cfg["neo4j"] = neo_cfg
            if isinstance(mem_cfg.get("cold_layer"), dict):
                cold_cfg = dict(mem_cfg.get("cold_layer") or {})
                cold_cfg.pop("summary_model", None)
                mem_cfg["cold_layer"] = cold_cfg
            cfg["memory"] = mem_cfg

        return cfg

    def _legacy_config_path(self, user_uuid: str) -> Path:
        return self.users_dir / f"{user_uuid}.json"

    def _current_config_path(self, user_uuid: str) -> Path:
        return self.users_dir / user_uuid / "config.json"

    def get_user_config(self, user_uuid: str) -> Dict[str, Any]:
        current_path = self._current_config_path(user_uuid)
        legacy_path = self._legacy_config_path(user_uuid)
        config_path = current_path if current_path.exists() else legacy_path

        if not config_path.exists():
            user = self.get_user_by_id(user_uuid)
            agent_name = user.get("agent_name", "Promethea") if user else "Promethea"
            self.create_user_config(user_uuid, agent_name)
            config_path = self._current_config_path(user_uuid)

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Read user config failed: {e}")
            # Auto-heal corrupted/truncated config files to avoid repeated runtime failures.
            try:
                if config_path.exists():
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                    backup_path = config_path.with_suffix(f".corrupt-{stamp}.json")
                    shutil.move(str(config_path), str(backup_path))
                    logger.warning(f"Corrupted user config moved to backup: {backup_path}")
                user = self.get_user_by_id(user_uuid)
                agent_name = user.get("agent_name", "Promethea") if user else "Promethea"
                self.create_user_config(user_uuid, agent_name)
                healed_path = self._current_config_path(user_uuid)
                with open(healed_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as heal_err:
                logger.error(f"Failed to auto-heal user config for {user_uuid}: {heal_err}")
            return {}

    def update_user_config_file(self, user_uuid: str, config_data: Dict[str, Any]) -> bool:
        config_path = self._current_config_path(user_uuid)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        current_config = self.get_user_config(user_uuid)
        sanitized = dict(config_data or {})
        # API credentials are env-only, never persisted per-user.
        if isinstance(sanitized.get("api"), dict):
            api_cfg = dict(sanitized["api"])
            api_cfg.pop("api_key", None)
            if api_cfg:
                sanitized["api"] = api_cfg
            else:
                sanitized.pop("api", None)
        if isinstance(sanitized.get("memory"), dict):
            mem = dict(sanitized["memory"])
            if isinstance(mem.get("api"), dict):
                mem_api = dict(mem["api"])
                mem_api.pop("api_key", None)
                if mem_api:
                    mem["api"] = mem_api
                else:
                    mem.pop("api", None)
            if isinstance(mem.get("neo4j"), dict):
                neo = dict(mem["neo4j"])
                neo.pop("password", None)
                if neo:
                    mem["neo4j"] = neo
                else:
                    mem.pop("neo4j", None)
            if mem:
                sanitized["memory"] = mem
            else:
                sanitized.pop("memory", None)
        current_config = self._deep_merge(current_config, sanitized)

        try:
            self._write_json_atomic(config_path, current_config)
            return True
        except Exception as e:
            logger.error(f"Update user config failed: {e}")
            return False

    @staticmethod
    def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(target, dict):
            target = {}
        if not isinstance(source, dict):
            return target
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                UserManager._deep_merge(target[key], value)
            else:
                target[key] = value
        return target

    def verify_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        user = self.get_user_by_username(username)
        if not user:
            return None
        try:
            if pwd_context.verify(password, user.get("password_hash")):
                return user
        except (MissingBackendError, ValueError):
            # Verify PBKDF2 hashes even if bcrypt backend is unavailable/incompatible.
            fallback_ctx = CryptContext(
                schemes=["pbkdf2_sha256"],
                default="pbkdf2_sha256",
                deprecated="auto",
            )
            if fallback_ctx.verify(password, user.get("password_hash")):
                return user
        return None

    def update_user_config(
        self,
        user_id: str,
        agent_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> bool:
        file_user_id = user_id.replace("user_", "", 1) if user_id.startswith("user_") else user_id
        try:
            if not self.identity_store.update_profile(
                file_user_id,
                agent_name=agent_name,
                system_prompt=system_prompt,
            ):
                return False
        except Exception as e:
            logger.error(f"Update identity profile failed: {e}")
            return False

        file_updates: Dict[str, Any] = {}
        if agent_name:
            file_updates["agent_name"] = agent_name
        if system_prompt:
            file_updates["system_prompt"] = system_prompt
        return self.update_user_config_file(file_user_id, file_updates)

    def bind_channel_account(self, user_id: str, channel: str, account_id: str) -> bool:
        try:
            return self.identity_store.bind_channel(user_id, channel, account_id)
        except Exception as e:
            logger.error(f"Bind channel account failed: {e}")
            return False

    def get_bound_channels(self, user_id: str) -> Dict[str, str]:
        try:
            return self.identity_store.get_channels(user_id)
        except Exception as e:
            logger.error(f"Get bound channels failed: {e}")
            return {}

    def get_user_by_channel_account(self, channel: str, account_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self.identity_store.get_by_channel(channel, account_id)
        except Exception as e:
            logger.error(f"Get user by channel account failed: {e}")
            return None

    def delete_user(self, user_id: str) -> bool:
        """
        Delete a user account and related local state owned by that user.
        """
        graph_user_id = user_id if user_id.startswith("user_") else f"user_{user_id}"
        raw_user_id = graph_user_id.replace("user_", "", 1)

        if self.connector is not None:
            try:
                self._delete_graph_user_subgraph(graph_user_id)
            except Exception as e:
                logger.error(f"Delete user graph data failed: {e}")
                return False

        try:
            if not self.identity_store.delete(raw_user_id):
                logger.warning(f"Identity not found during delete: {raw_user_id}")
        except Exception as e:
            logger.error(f"Delete identity failed: {e}")
            return False

        try:
            config_dir = self._current_config_path(raw_user_id).parent
            if config_dir.exists():
                shutil.rmtree(config_dir, ignore_errors=True)
            legacy_path = self._legacy_config_path(raw_user_id)
            if legacy_path.exists():
                legacy_path.unlink(missing_ok=True)
            self._cleanup_user_local_state(raw_user_id=raw_user_id, graph_user_id=graph_user_id)
            projects_path = self.users_dir / "projects.sqlite3"
            if projects_path.exists():
                from .project_store import ProjectStore
                ProjectStore(projects_path).clear_user(raw_user_id)
        except Exception as e:
            logger.warning(f"Delete user local state cleanup failed: {e}")

        logger.info(f"User deleted: {graph_user_id}")
        return True

    def _delete_graph_user_subgraph(self, graph_user_id: str) -> None:
        """
        Delete the user and the memory/session subgraph exclusively reachable
        through sessions owned by that user.
        """
        self.connector.query(
            """
            MATCH (u:User {id: $user_id})
            OPTIONAL MATCH (s:Session)-[:OWNED_BY]->(u)
            OPTIONAL MATCH (n)-[:PART_OF_SESSION]->(s)
            OPTIONAL MATCH (x)-[:FROM_MESSAGE]->(n)
            OPTIONAL MATCH (sum:Summary)-[:SUMMARIZES]->(s)
            WITH collect(DISTINCT u) + collect(DISTINCT s) + collect(DISTINCT n)
               + collect(DISTINCT x) + collect(DISTINCT sum) AS nodes
            UNWIND nodes AS node
            WITH DISTINCT node
            WHERE node IS NOT NULL
            DETACH DELETE node
            """,
            {"user_id": graph_user_id},
        )

    def _cleanup_user_local_state(self, *, raw_user_id: str, graph_user_id: str) -> None:
        project_root = self._cleanup_project_root()
        candidates = [
            project_root / "logs" / raw_user_id,
            project_root / "logs" / graph_user_id,
            project_root / "workspace" / raw_user_id,
            project_root / "workspace" / graph_user_id,
        ]
        for target in candidates:
            try:
                resolved = target.resolve()
                allowed_roots = [
                    (project_root / "logs").resolve(),
                    (project_root / "workspace").resolve(),
                ]
                if not any(resolved == root or root in resolved.parents for root in allowed_roots):
                    continue
                if resolved.exists() and resolved.is_dir():
                    shutil.rmtree(resolved, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Delete user cleanup skipped {target}: {e}")

        template_dir = project_root / "brain" / "basal_ganglia" / "reasoning_templates"
        learning_root = project_root / "brain" / "basal_ganglia" / "moirai_learning"
        if (learning_root / "learning.sqlite3").exists():
            from agentkit.tools.moirai.learning import MoiraiLearning

            learning = MoiraiLearning(learning_root)
            for user_key in (raw_user_id, graph_user_id):
                learning.purge_user(user_key)
        for suffix in ("templates.json", "paths.jsonl", "opro.json"):
            for user_key in (raw_user_id, graph_user_id):
                target = template_dir / f"{self._safe_file_segment(user_key)}.{suffix}"
                try:
                    if target.exists() and target.is_file():
                        target.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Delete user template cleanup skipped {target}: {e}")

        moirai_dir = project_root / "brain" / "basal_ganglia" / "moirai_runs"
        for prefix in ("opro_episode", "opro_profile"):
            for user_key in (raw_user_id, graph_user_id):
                target = moirai_dir / f"{prefix}_{self._safe_file_segment(user_key)}.json"
                try:
                    if target.exists() and target.is_file():
                        target.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Delete user moirai cleanup skipped {target}: {e}")

    @staticmethod
    def _cleanup_project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _safe_file_segment(value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or ""))


user_manager = UserManager()


