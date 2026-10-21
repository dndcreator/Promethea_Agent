"""Owner-scoped navigation metadata, separate from execution workspaces."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class ProjectStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    user_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, project_id)
                );
                CREATE TABLE IF NOT EXISTS project_sessions (
                    user_id TEXT NOT NULL, session_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    PRIMARY KEY (user_id, session_id),
                    FOREIGN KEY (user_id, project_id) REFERENCES projects(user_id, project_id) ON DELETE CASCADE
                );
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _name(name: str) -> str:
        value = str(name).strip()
        if not value or len(value) > 100:
            raise ValueError("Project name must contain 1-100 characters")
        return value

    def list(self, user_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT project_id,name,created_at,updated_at FROM projects WHERE user_id=? ORDER BY created_at,project_id", (user_id,)).fetchall()
            memberships = db.execute("SELECT project_id,session_id FROM project_sessions WHERE user_id=? ORDER BY session_id", (user_id,)).fetchall()
        result = {row["project_id"]: {**dict(row), "session_ids": []} for row in rows}
        for row in memberships:
            result[row["project_id"]]["session_ids"].append(row["session_id"])
        return list(result.values())

    def create(self, user_id: str, name: str) -> dict:
        project_id = f"project_{uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        value = {"project_id": project_id, "name": self._name(name), "created_at": now, "updated_at": now, "session_ids": []}
        with self._connect() as db:
            db.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (user_id, project_id, value["name"], now, now))
        return value

    def rename(self, user_id: str, project_id: str, name: str) -> bool:
        with self._connect() as db:
            return db.execute("UPDATE projects SET name=?,updated_at=? WHERE user_id=? AND project_id=?", (self._name(name), datetime.now(timezone.utc).isoformat(), user_id, project_id)).rowcount > 0

    def delete(self, user_id: str, project_id: str) -> bool:
        with self._connect() as db:
            return db.execute("DELETE FROM projects WHERE user_id=? AND project_id=?", (user_id, project_id)).rowcount > 0

    def assign(self, user_id: str, session_id: str, project_id: str | None) -> None:
        with self._connect() as db:
            if project_id is None:
                db.execute("DELETE FROM project_sessions WHERE user_id=? AND session_id=?", (user_id, session_id))
                return
            if db.execute("SELECT 1 FROM projects WHERE user_id=? AND project_id=?", (user_id, project_id)).fetchone() is None:
                raise KeyError("Project not found")
            db.execute("INSERT INTO project_sessions VALUES (?,?,?) ON CONFLICT(user_id,session_id) DO UPDATE SET project_id=excluded.project_id", (user_id, session_id, project_id))

    def clear_user(self, user_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM projects WHERE user_id=?", (user_id,))

    @classmethod
    def validate_records(cls, rows: list[dict]) -> list[dict]:
        if not isinstance(rows, list):
            raise ValueError("Invalid project records")
        prepared = []
        project_ids, memberships = set(), set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid project record")
            project_id = str(row.get("project_id") or "").strip()
            if not project_id or len(project_id) > 200:
                raise ValueError("Invalid project identifier")
            session_ids = row.get("session_ids") or []
            if not isinstance(session_ids, list) or any(not isinstance(item, str) or not item for item in session_ids):
                raise ValueError("Invalid project memberships")
            if project_id in project_ids or any(item in memberships for item in session_ids):
                raise ValueError("Duplicate project or membership")
            project_ids.add(project_id)
            memberships.update(session_ids)
            prepared.append({**row, "project_id": project_id, "name": cls._name(row.get("name", "")), "session_ids": sorted(set(session_ids))})
        return prepared

    def import_records(self, user_id: str, rows: list[dict], *, merge: bool = True, owned_session_ids: set[str]) -> None:
        prepared = self.validate_records(rows)
        with self._connect() as db:
            if not merge:
                db.execute("DELETE FROM projects WHERE user_id=?", (user_id,))
            for row in prepared:
                project_id, name = row["project_id"], row["name"]
                now = datetime.now(timezone.utc).isoformat()
                db.execute("INSERT INTO projects VALUES (?,?,?,?,?) ON CONFLICT(user_id,project_id) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at", (user_id, project_id, name, str(row.get("created_at") or now), str(row.get("updated_at") or now)))
                for session_id in row.get("session_ids") or []:
                    if str(session_id) in owned_session_ids:
                        db.execute("INSERT INTO project_sessions VALUES (?,?,?) ON CONFLICT(user_id,session_id) DO UPDATE SET project_id=excluded.project_id", (user_id, str(session_id), project_id))
