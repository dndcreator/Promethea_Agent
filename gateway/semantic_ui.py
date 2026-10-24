"""Structured expression over the host UI; not a tool executor or app builder."""
from __future__ import annotations

from datetime import datetime, timezone

from .protocol import EventType
from .public_contracts import SemanticExpression, SemanticUIState
from .task_service import TaskExecutionConflict


class SemanticUI:
    def __init__(self, *, store, message_manager=None, event_emitter=None, environment=None):
        self.store, self.messages, self.events = store, message_manager, event_emitter
        self.environment = environment

    def _target(self, user, session_id, message_id=None):
        if message_id and not session_id:
            raise ValueError("a message anchor requires its conversation")
        if session_id:
            session = self.messages.get_session(session_id, user_id=user) if self.messages else None
            if session is None:
                raise KeyError("conversation not found")
            if message_id and not any(row.get("id") == message_id for row in session.get("messages", [])):
                raise KeyError("message anchor not found")

    def view(self, user):
        current = self.store.get(user)
        return SemanticUIState(revision=current.revision, expressions=list(current.expressions.values())).model_dump()

    def context_projection(self, user):
        current = self.store.get(user)
        rows = list(current.expressions.values())
        return {
            "revision": current.revision,
            "recent_responses": [{"expression_id": item.expression_id, "response": item.response, "state": item.state} for item in rows if item.state != "open"][-6:],
            "open_expressions": [{"expression_id": item.expression_id, "revision": item.revision, "kind": item.kind, "content": item.content[:240], "session_id": item.session_id, "message_id": item.message_id} for item in rows if item.state == "open" and not item.hidden][-8:],
            "retained_count": len(rows),
        }

    async def _emit(self, event, user, **payload):
        if self.events is not None:
            await self.events.emit(event, {"user_id": user, **payload})

    async def present(self, user, command):
        self._target(user, command.session_id, command.message_id)
        result = None
        before = self.store.get(user).revision
        def apply(current):
            nonlocal result
            previous = current.expressions.get(command.expression_id)
            revision = previous.revision if previous else 0
            values = command.model_dump()
            if previous and previous.expected_revision == command.expected_revision and all(previous.model_dump()[key] == value for key, value in values.items()):
                result = previous
                return
            if revision != command.expected_revision:
                raise TaskExecutionConflict("expression revision changed; inspect before updating")
            if not previous and len(current.expressions) >= 64:
                # Retain active interactions; only settled presentation may be evicted.
                settled = next((key for key, item in current.expressions.items() if item.state != "open" or item.hidden), None)
                if settled is None:
                    raise ValueError("expression capacity reached; hide or reuse an existing expression")
                del current.expressions[settled]
            result = SemanticExpression(**values, revision=revision + 1, updated_at=datetime.now(timezone.utc).isoformat())
            current.expressions[command.expression_id] = result
        current = self.store.update(user, apply)
        if current.revision != before:
            await self._emit(EventType.SEMANTIC_UI_UPDATED, user, expression_id=command.expression_id, revision=current.revision, session_id=command.session_id)
        return result.model_dump()

    async def feedback(self, user, expression_id, command):
        result = None
        before = self.store.get(user).revision
        def apply(current):
            nonlocal result
            item = current.expressions.get(expression_id)
            if item is None:
                raise KeyError("expression not found")
            if command.action == "dismiss" and command.choice_id is not None:
                raise ValueError("dismiss does not accept a choice")
            response = command.choice_id if command.action == "respond" else item.response
            state = "responded" if command.action == "respond" else "dismissed"
            if item.state == state and item.response == response and item.revision == command.expected_revision + 1:
                result = item
                return
            if item.revision != command.expected_revision or item.state == "dismissed" or item.hidden or (command.action == "respond" and item.state != "open"):
                raise TaskExecutionConflict("expression changed; reload before responding")
            if command.action == "respond" and (item.kind != "choice" or response not in {choice.id for choice in item.choices}):
                raise ValueError("response must select a declared choice")
            item.state, item.response = state, response
            item.revision += 1
            item.updated_at = datetime.now(timezone.utc).isoformat()
            current.feedback = [*current.feedback, {"expression_id": expression_id, "content": item.content, "response": response, "state": state}][-30:]
            result = item
        current = self.store.update(user, apply)
        if current.revision != before:
            await self._emit(EventType.SEMANTIC_UI_INTERACTED, user, expression_id=expression_id, revision=current.revision, session_id=result.session_id, state=result.state, response=result.response)
        return result.model_dump()

    async def observe_surface(self, user, surface):
        self._target(user, surface.session_id, surface.message_id)
        if self.environment is None:
            raise RuntimeError("environment projection is unavailable")
        changed = await self.environment.observe(user, surface)
        if changed:
            await self._emit(EventType.UI_CONTEXT_CHANGED, user, session_id=surface.session_id, message_id=surface.message_id, surface_id=surface.surface_id, view=surface.view)
        return {"ok": True}
