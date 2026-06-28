import json
import os
import uuid
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger
from passlib.context import CryptContext
from passlib.exc import MissingBackendError

from config import load_config
from memory.models import Neo4jNode, NodeType
from memory.neo4j_connector import Neo4jConnectionPool
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
        self.store_backend = str(getattr(cfg.memory, "store_backend", "neo4j") or "neo4j").strip().lower()
        self.connector = Neo4jConnectionPool.get_connector(cfg.memory.neo4j)
        if not self.connector:
            logger.warning("Neo4j is unavailable, user graph operations are disabled")

        self.users_dir = Path(__file__).resolve().parents[2] / "config" / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def _use_graph_users(self) -> bool:
        return self.store_backend == "neo4j" and self.connector is not None

    def _use_local_users(self) -> bool:
        return self.store_backend in {"sqlite_graph", "flat_memory"}

    def can_register(self) -> tuple[bool, str]:
        if self._use_graph_users() or self._use_local_users():
            return True, ""
        if self.store_backend == "neo4j":
            neo4j_error = Neo4jConnectionPool.get_last_error()
            reason = neo4j_error.get("code") or "neo4j_user_backend_unavailable"
            return False, reason
        return False, "user_backend_unavailable"

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

    def _save_local_users(self, data: Dict[str, Any]) -> None:
        self._write_json_atomic(self._local_users_path(), data)

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        if self._use_local_users():
            data = self._load_local_users()
            for user in data.get("users") or []:
                if isinstance(user, dict) and user.get("username") == username:
                    return user
            return None

        if not self._use_graph_users():
            return None

        query = "MATCH (u:User {username: $username}) RETURN u"
        results = self.connector.query(query, {"username": username})
        return results[0]["u"] if results else None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        if self._use_local_users():
            raw_user_id = user_id.replace("user_", "", 1) if user_id.startswith("user_") else user_id
            data = self._load_local_users()
            for user in data.get("users") or []:
                if isinstance(user, dict) and user.get("user_id") == raw_user_id:
                    return user
            return None

        if not self._use_graph_users():
            return None

        if not user_id.startswith("user_"):
            user_id = f"user_{user_id}"

        query = "MATCH (u:User {id: $user_id}) RETURN u"
        results = self.connector.query(query, {"user_id": user_id})
        return results[0]["u"] if results else None

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

        if self._use_local_users():
            data = self._load_local_users()
            users = list(data.get("users") or [])
            users.append(
                {
                    "id": f"user_{raw_uuid}",
                    "username": username,
                    "password_hash": password_hash,
                    "agent_name": agent_name,
                    "user_id": raw_uuid,
                    "auth_backend": "local_file",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            data["users"] = users
            try:
                self._save_local_users(data)
                self.create_user_config(raw_uuid, agent_name)
                logger.info(f"Local user created: user_{raw_uuid}")
                return raw_uuid
            except Exception as e:
                logger.error(f"Create local user failed: {e}")
                return None

        try:
            user_node = Neo4jNode(
                id=f"user_{raw_uuid}",
                type=NodeType.USER,
                content=f"user {username}",
                properties={
                    "username": username,
                    "password_hash": password_hash,
                    "agent_name": agent_name,
                    "user_id": raw_uuid,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.connector.create_node(user_node)
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
        if not self.connector:
            return False

        if not user_id.startswith("user_"):
            neo4j_user_id = f"user_{user_id}"
            file_user_id = user_id
        else:
            neo4j_user_id = user_id
            file_user_id = user_id.replace("user_", "", 1)

        updates = []
        params = {"user_id": neo4j_user_id}
        if agent_name:
            updates.append("u.agent_name = $agent_name")
            params["agent_name"] = agent_name
        if system_prompt:
            updates.append("u.system_prompt = $system_prompt")
            params["system_prompt"] = system_prompt

        if updates:
            query = f"MATCH (u:User {{id: $user_id}}) SET {', '.join(updates)} RETURN u"
            try:
                self.connector.query(query, params)
            except Exception as e:
                logger.error(f"Update Neo4j user config failed: {e}")
                return False

        file_updates: Dict[str, Any] = {}
        if agent_name:
            file_updates["agent_name"] = agent_name
        if system_prompt:
            file_updates["system_prompt"] = system_prompt
        return self.update_user_config_file(file_user_id, file_updates)

    def bind_channel_account(self, user_id: str, channel: str, account_id: str) -> bool:
        if not self.connector:
            return False

        if not user_id.startswith("user_"):
            user_id = f"user_{user_id}"

        prop_name = f"channel_{channel}"
        query = f"MATCH (u:User {{id: $user_id}}) SET u.{prop_name} = $account_id RETURN u"
        try:
            self.connector.query(query, {"user_id": user_id, "account_id": account_id})
            return True
        except Exception as e:
            logger.error(f"Bind channel account failed: {e}")
            return False

    def get_bound_channels(self, user_id: str) -> Dict[str, str]:
        if not self.connector:
            return {}

        if not user_id.startswith("user_"):
            user_id = f"user_{user_id}"

        query = "MATCH (u:User {id: $user_id}) RETURN u"
        try:
            results = self.connector.query(query, {"user_id": user_id})
            if not results:
                return {}

            user_props = results[0]["u"]
            channels: Dict[str, str] = {}
            for key, value in user_props.items():
                if key.startswith("channel_"):
                    channels[key.replace("channel_", "")] = value
            return channels
        except Exception as e:
            logger.error(f"Get bound channels failed: {e}")
            return {}

    def get_user_by_channel_account(self, channel: str, account_id: str) -> Optional[Dict[str, Any]]:
        if not self.connector:
            return None

        prop_name = f"channel_{channel}"
        query = f"MATCH (u:User) WHERE u.{prop_name} = $account_id RETURN u"
        try:
            results = self.connector.query(query, {"account_id": account_id})
            return results[0]["u"] if results else None
        except Exception as e:
            logger.error(f"Get user by channel account failed: {e}")
            return None

    def delete_user(self, user_id: str) -> bool:
        """
        Delete a user account and related local state owned by that user.
        """
        graph_user_id = user_id if user_id.startswith("user_") else f"user_{user_id}"
        raw_user_id = graph_user_id.replace("user_", "", 1)

        if self._use_local_users():
            data = self._load_local_users()
            users = list(data.get("users") or [])
            kept = [
                user
                for user in users
                if not (
                    isinstance(user, dict)
                    and str(user.get("user_id") or "") == raw_user_id
                )
            ]
            if len(kept) == len(users):
                logger.warning(f"Local user not found during delete: {raw_user_id}")
            data["users"] = kept
            try:
                self._save_local_users(data)
            except Exception as e:
                logger.error(f"Delete local user failed: {e}")
                return False
        elif self._use_graph_users():
            try:
                self._delete_graph_user_subgraph(graph_user_id)
            except Exception as e:
                logger.error(f"Delete user graph data failed: {e}")
                return False
        else:
            logger.error("User backend unavailable, cannot delete user")
            return False

        try:
            config_dir = self._current_config_path(raw_user_id).parent
            if config_dir.exists():
                shutil.rmtree(config_dir, ignore_errors=True)
            legacy_path = self._legacy_config_path(raw_user_id)
            if legacy_path.exists():
                legacy_path.unlink(missing_ok=True)
            self._cleanup_user_local_state(raw_user_id=raw_user_id, graph_user_id=graph_user_id)
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


