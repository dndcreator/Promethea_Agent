from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class IdentityStore:
    """Backend-independent account and channel identity storage."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS identities (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    agent_name TEXT NOT NULL DEFAULT 'Promethea',
                    system_prompt TEXT,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS channel_bindings (
                    user_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    PRIMARY KEY (user_id, channel),
                    UNIQUE (channel, account_id),
                    FOREIGN KEY (user_id) REFERENCES identities(user_id) ON DELETE CASCADE
                );
                """
            )

    @staticmethod
    def _raw_user_id(value: Any) -> str:
        user_id = str(value or "").strip()
        return user_id.removeprefix("user_")

    @staticmethod
    def _as_user(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        raw_user_id = str(row["user_id"])
        metadata = json.loads(str(row["metadata_json"] or "{}"))
        return {
            **(metadata if isinstance(metadata, dict) else {}),
            "id": f"user_{raw_user_id}",
            "user_id": raw_user_id,
            "username": str(row["username"]),
            "password_hash": str(row["password_hash"]),
            "agent_name": str(row["agent_name"] or "Promethea"),
            "system_prompt": row["system_prompt"],
            "created_at": str(row["created_at"]),
            "auth_backend": "identity_sqlite",
        }

    def get_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM identities WHERE username = ?",
                (str(username),),
            ).fetchone()
        return self._as_user(row)

    def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        raw_user_id = self._raw_user_id(user_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM identities WHERE user_id = ?",
                (raw_user_id,),
            ).fetchone()
        return self._as_user(row)

    def create(self, user: Dict[str, Any]) -> str:
        raw_user_id = self._raw_user_id(user.get("user_id") or user.get("id"))
        if not raw_user_id:
            raise ValueError("user_id is required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO identities (
                    user_id, username, password_hash, agent_name,
                    system_prompt, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_user_id,
                    str(user.get("username") or ""),
                    str(user.get("password_hash") or ""),
                    str(user.get("agent_name") or "Promethea"),
                    user.get("system_prompt"),
                    str(user.get("created_at") or ""),
                    "{}",
                ),
            )
        return raw_user_id

    def import_legacy(self, users: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        imported = 0
        existing = 0
        conflicts = 0
        for user in users:
            if not isinstance(user, dict):
                continue
            raw_user_id = self._raw_user_id(user.get("user_id") or user.get("id"))
            username = str(user.get("username") or "").strip()
            password_hash = str(user.get("password_hash") or "").strip()
            if not raw_user_id or not username or not password_hash:
                continue
            current_by_id = self.get_by_id(raw_user_id)
            current_by_name = self.get_by_username(username)
            if current_by_id or current_by_name:
                if (
                    current_by_id
                    and current_by_name
                    and current_by_id["user_id"] == current_by_name["user_id"] == raw_user_id
                ):
                    existing += 1
                else:
                    conflicts += 1
                continue
            self.create(user)
            imported += 1
        return {"imported": imported, "existing": existing, "conflicts": conflicts}

    def update_profile(
        self,
        user_id: str,
        *,
        agent_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> bool:
        assignments = []
        values = []
        if agent_name is not None:
            assignments.append("agent_name = ?")
            values.append(str(agent_name))
        if system_prompt is not None:
            assignments.append("system_prompt = ?")
            values.append(str(system_prompt))
        if not assignments:
            return self.get_by_id(user_id) is not None
        values.append(self._raw_user_id(user_id))
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE identities SET {', '.join(assignments)} WHERE user_id = ?",
                values,
            )
        return cursor.rowcount > 0

    def bind_channel(self, user_id: str, channel: str, account_id: str) -> bool:
        raw_user_id = self._raw_user_id(user_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO channel_bindings (user_id, channel, account_id)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, channel) DO UPDATE SET account_id = excluded.account_id
                """,
                (raw_user_id, str(channel), str(account_id)),
            )
        return True

    def get_channels(self, user_id: str) -> Dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT channel, account_id FROM channel_bindings WHERE user_id = ?",
                (self._raw_user_id(user_id),),
            ).fetchall()
        return {str(row["channel"]): str(row["account_id"]) for row in rows}

    def get_by_channel(self, channel: str, account_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT i.* FROM identities AS i
                JOIN channel_bindings AS c ON c.user_id = i.user_id
                WHERE c.channel = ? AND c.account_id = ?
                """,
                (str(channel), str(account_id)),
            ).fetchone()
        return self._as_user(row)

    def delete(self, user_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM identities WHERE user_id = ?",
                (self._raw_user_id(user_id),),
            )
        return cursor.rowcount > 0
