"""Personal working cognition and communicative intent, never domain truth."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .public_contracts import SemanticExpression


class WorkingSituation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = 0
    cognition_revision: int = 0
    attention: list[str] = Field(default_factory=list, max_length=6)
    questions: list[str] = Field(default_factory=list, max_length=8)
    interpretation: str = Field(default="", max_length=4000)
    feedback: list[dict] = Field(default_factory=list, max_length=30)
    changes: list[dict] = Field(default_factory=list, max_length=24)
    last_event_seq: int = 0
    expressions: dict[str, SemanticExpression] = Field(default_factory=dict, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_surface(cls, value):
        return {key: item for key, item in value.items() if key != "surface"} if isinstance(value, dict) else value

    @field_validator("attention", "questions")
    @classmethod
    def bounded_text(cls, values):
        if any(not value.strip() or len(value) > 800 for value in values):
            raise ValueError("working cognition items must contain 1-800 characters")
        return values


class SelfModelStateStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = RLock()
        raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"version": 1, "users": {}}
        if raw.get("version") != 1:
            raise ValueError("unsupported self-model state version")
        self.users = {user: WorkingSituation.model_validate(row) for user, row in raw["users"].items()}

    def get(self, user):
        with self._lock:
            return self.users.get(user, WorkingSituation()).model_copy(deep=True)

    def update(self, user, change, *, expected_revision=None):
        from .task_service import TaskExecutionConflict

        with self._lock:
            previous = self.users.get(user)
            current = self.get(user)
            if expected_revision is not None and current.cognition_revision != expected_revision:
                raise TaskExecutionConflict("self-model revision changed; read current context before updating")
            change(current)
            if previous is not None and current == previous:
                return current
            current.revision += 1
            current = WorkingSituation.model_validate(current.model_dump())
            self.users[user] = current
            try:
                self._save()
            except Exception:
                if previous is None:
                    self.users.pop(user, None)
                else:
                    self.users[user] = previous
                raise
            return current.model_copy(deep=True)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".self-model-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "users": {user: row.model_dump() for user, row in self.users.items()}}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def export_user_state(self, user):
        return {"version": 1, "situation": self.get(user).model_dump()}

    def import_user_state(self, user, payload, *, merge=True):
        if payload.get("version") != 1:
            raise ValueError("unsupported self-model transfer version")
        incoming = WorkingSituation.model_validate(payload["situation"])
        if merge and user in self.users:
            return
        # An imported surface is not evidence of what is currently visible.
        incoming.changes, incoming.last_event_seq = [], 0
        def replace(current):
            for name in WorkingSituation.model_fields:
                if name != "revision":
                    setattr(current, name, getattr(incoming, name))
            current.cognition_revision += 1
        self.update(user, replace)

    def purge_user_state(self, user):
        with self._lock:
            previous = self.users.pop(user, None)
            try:
                self._save()
            except Exception:
                if previous is not None:
                    self.users[user] = previous
                raise
