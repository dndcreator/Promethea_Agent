import json
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger
from passlib.context import CryptContext
from passlib.exc import MissingBackendError

from config import load_config
from memory.models import Neo4jNode, NodeType
from memory.neo4j_connector import Neo4jConnectionPool

# Prefer bcrypt, with PBKDF2 fallback when bcrypt backend is unavailable.
pwd_context = CryptContext(
    schemes=["bcrypt", "pbkdf2_sha256"],
    default="bcrypt",
    deprecated="auto",
)


class UserManager:
    def __init__(self):
        cfg = load_config()
        self.connector = Neo4jConnectionPool.get_connector(cfg.memory.neo4j)
        if not self.connector:
            logger.warning("Neo4j is unavailable, user graph operations are disabled")

        self.users_dir = Path("config/users")
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        if not self.connector:
            return None

        query = "MATCH (u:User {username: $username}) RETURN u"
        results = self.connector.query(query, {"username": username})
        return results[0]["u"] if results else None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not self.connector:
            return None

        if not user_id.startswith("user_"):
            user_id = f"user_{user_id}"

        query = "MATCH (u:User {id: $user_id}) RETURN u"
        results = self.connector.query(query, {"user_id": user_id})
        return results[0]["u"] if results else None

    def create_user(self, username: str, password: str, agent_name: str = "Promethea") -> Optional[str]:
        if not self.connector:
            logger.error("Neo4j is unavailable, cannot create user")
            return None

        if self.get_user_by_username(username):
            logger.warning(f"User already exists: {username}")
            return None

        try:
            password_hash = pwd_context.hash(password)
        except (MissingBackendError, ValueError):
            # Fallback when bcrypt backend is missing or runtime-incompatible.
            fallback_ctx = CryptContext(
                schemes=["pbkdf2_sha256"],
                default="pbkdf2_sha256",
                deprecated="auto",
            )
            password_hash = fallback_ctx.hash(password)
        raw_uuid = str(uuid.uuid4())
        user_id = f"user_{raw_uuid}"

        user_node = Neo4jNode(
            id=user_id,
            type=NodeType.USER,
            content=f"user {username}",
            properties={
                "username": username,
                "password_hash": password_hash,
                "agent_name": agent_name,
                "user_id": raw_uuid,
                "created_at": datetime.now().isoformat(),
            },
        )

        try:
            self.connector.create_node(user_node)
            self.create_user_config(raw_uuid, agent_name)
            logger.info(f"User created: {user_id}")
            return raw_uuid
        except Exception as e:
            logger.error(f"Create user failed: {e}")
            return None

    def create_user_config(self, user_uuid: str, agent_name: str):
        user_dir = self.users_dir / user_uuid
        user_dir.mkdir(parents=True, exist_ok=True)
        config_path = user_dir / "config.json"

        default_config = {
            "agent_name": agent_name,
            "system_prompt": "",
        }

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Create user config failed: {e}")

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
            return {}

    def update_user_config_file(self, user_uuid: str, config_data: Dict[str, Any]) -> bool:
        config_path = self._current_config_path(user_uuid)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        current_config = self.get_user_config(user_uuid)
        sanitized = dict(config_data or {})
        # API credentials are global (env), never persisted per-user.
        sanitized.pop("api", None)
        if isinstance(sanitized.get("memory"), dict):
            mem = dict(sanitized["memory"])
            mem.pop("api", None)
            if mem:
                sanitized["memory"] = mem
            else:
                sanitized.pop("memory", None)
        current_config = self._deep_merge(current_config, sanitized)

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(current_config, f, indent=4, ensure_ascii=False)
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
        Delete a user account and related local config files.
        """
        if not self.connector:
            logger.error("Neo4j is unavailable, cannot delete user")
            return False

        graph_user_id = user_id if user_id.startswith("user_") else f"user_{user_id}"
        raw_user_id = graph_user_id.replace("user_", "", 1)
        try:
            self.connector.query(
                """
                MATCH (u:User {id: $user_id})
                OPTIONAL MATCH (s:Session)-[:OWNED_BY]->(u)
                DETACH DELETE s, u
                """,
                {"user_id": graph_user_id},
            )
        except Exception as e:
            logger.error(f"Delete user graph data failed: {e}")
            return False

        try:
            config_dir = self._current_config_path(raw_user_id).parent
            if config_dir.exists():
                shutil.rmtree(config_dir, ignore_errors=True)
            legacy_path = self._legacy_config_path(raw_user_id)
            if legacy_path.exists():
                legacy_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Delete user local config cleanup failed: {e}")

        logger.info(f"User deleted: {graph_user_id}")
        return True


user_manager = UserManager()
