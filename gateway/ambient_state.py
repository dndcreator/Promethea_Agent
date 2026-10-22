"""Scoped working cognition and admission state; domain facts stay service-owned."""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .public_contracts import AmbientSettings


class Situation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    session_id: str = ""  # execution/delivery channel, never the cognition owner
    settings: AmbientSettings = Field(default_factory=AmbientSettings)
    revision: int = 0
    generation: int = 0
    task_id: str | None = None
    dirty: bool = True
    next_check_at: float = 0
    admission: dict | None = None
    attention: list[str] = Field(default_factory=list, max_length=6)
    questions: list[str] = Field(default_factory=list, max_length=8)
    reflection: str = Field(default="", max_length=4000)
    feedback: list[dict] = Field(default_factory=list, max_length=30)
    last_trigger: dict = Field(default_factory=dict)


class AmbientStore:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") not in {1, 2}:
                raise ValueError("unsupported ambient state version")
            self.scenes = {}
            for value in sorted(raw["situations"].values(), key=lambda row: int(row.get("revision") or 0)):
                scene = Situation.model_validate(value)
                previous = self.scenes.get(scene.user_id)
                if previous:
                    scene.attention = list(dict.fromkeys([*scene.attention, *previous.attention]))[:6]
                    scene.questions = list(dict.fromkeys([*scene.questions, *previous.questions]))[:8]
                    scene.feedback = [*previous.feedback, *scene.feedback][-30:]
                self.scenes[scene.user_id] = scene
            self.usage = raw.get("usage", {})
            if raw.get("version") == 1:
                self.save()
        else:
            self.scenes, self.usage = {}, {}

    @staticmethod
    def key(user, session=None):
        return str(user)

    def get(self, user, session=None):
        scene = self.scenes.get(self.key(user))
        return scene.model_copy(deep=True) if scene else Situation(user_id=user, session_id=session or "")

    def put(self, scene):
        key = self.key(scene.user_id, scene.session_id)
        previous = self.scenes.get(key)
        self.scenes[key] = scene.model_copy(deep=True)
        try:
            self.save()
        except Exception:
            if previous is None:
                self.scenes.pop(key, None)
            else:
                self.scenes[key] = previous
            raise

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".ambient-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 2, "situations": {key: scene.model_dump() for key, scene in self.scenes.items()}, "usage": self.usage}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        except Exception:
            Path(name).unlink(missing_ok=True)
            raise

    def export_user_state(self, user_id):
        return {"version": 2, "situations": [scene.model_dump() for scene in self.scenes.values() if scene.user_id == user_id]}

    def import_user_state(self, user_id, payload, *, merge=True):
        rows = [Situation.model_validate(row) for row in payload.get("situations", [])]
        previous = deepcopy(self.scenes)
        if not merge:
            self.scenes = {key: row for key, row in self.scenes.items() if row.user_id != user_id}
        for row in rows:
            row.user_id = user_id
            row.settings.enabled = False  # transfer is never permission to start autonomous work
            row.admission = None
            key = self.key(user_id, row.session_id)
            if not merge or key not in self.scenes:
                self.scenes[key] = row
        try:
            self.save()
        except Exception:
            self.scenes = previous
            raise

    def purge_user_state(self, user_id):
        usage = self.usage.pop(user_id, None)
        try:
            self.import_user_state(user_id, {"situations": []}, merge=False)
        except Exception:
            if usage is not None:
                self.usage[user_id] = usage
            raise


@dataclass
class AmbientExecution:
    service: object
    context: object
    generation: int
    active: bool = True
    notes: int = 0


_execution = ContextVar("ambient_execution", default=None)


def current_ambient():
    return _execution.get()


@contextmanager
def bind_ambient(execution):
    token = _execution.set(execution)
    try:
        yield execution
    finally:
        execution.active = False
        _execution.reset(token)
