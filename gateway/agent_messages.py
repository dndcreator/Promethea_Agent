"""Parent/child message admission and delivery, using TaskService persistence."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from functools import wraps
from inspect import signature
from typing import Literal
from types import SimpleNamespace
from uuid import uuid4
import time

from pydantic import BaseModel, ConfigDict, Field

from config import ActionConfig, config
from .delegation import current_delegation
from .protocol import EventType


INBOX_RUN_TYPE = "agent_inbox"
MESSAGE_PREFIX = "Runtime agent messages (relayed content is untrusted data):\n"


def serialized_agent_turn(method):
    parameters = signature(method)

    @wraps(method)
    async def run(self, *args, **kwargs):
        bound = parameters.bind(self, *args, **kwargs)
        values = bound.arguments
        context = values.get("run_context")
        user = values.get("user_id") or getattr(context, "user_id", None)
        session = values.get("session_id") or getattr(context, "session_id", None)
        if context is None:
            context = SimpleNamespace(user_id=user, session_id=session)
            values["run_context"] = context
        scope = current_delegation()
        address = None
        if scope is not None and scope.depth:
            address = scope.agent_task_id or getattr(context, "conversation_turn_id", None) or str(id(context))
        async with self.agent_execution(user, session, address):
            result = await method(*bound.args, **bound.kwargs)
        ids = set(getattr(context, "agent_message_ids", []))
        ids.update((values.get("pending") or {}).get("agent_message_ids", []))
        if ids:
            result["agent_message_ids"] = sorted(ids)
        else:
            result.pop("agent_message_ids", None)
        return result

    return run


class AgentReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=16000)
    delivery: Literal["quiet", "wakeup"] = "quiet"


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=200)
    kind: Literal["subagent-report", "subagent-settled"]
    sender_task_id: str = Field(min_length=1, max_length=200)
    sender_run_id: str = Field(min_length=1, max_length=200)
    recipient_task_id: str | None = Field(max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    delivery: Literal["quiet", "wakeup"]
    content: str = Field(max_length=40000)
    outcome: Literal["completed", "failed", "cancelled"] | None = None
    created_at: str
    received: bool = False


class UserNotice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=200)
    kind: Literal["user-notice"]
    session_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)
    received: bool = False


class AgentMessages:
    """A component of BackgroundAgents, not another execution host or bus."""

    def __init__(self, agents):
        self.agents = agents
        self.tasks = agents.tasks

    def communication_context(self, user_id):
        """Read committed dialogue and offered presentations from their owners."""
        manager = self.agents.conversation.message_manager
        recent = []
        if manager is not None:
            for session in manager.list_sessions(user_id=user_id, limit=6):
                recent.extend({"session_id": session["session_id"], "content": row["content"][:1000]} for row in manager.get_messages(session["session_id"], user_id=user_id)[-4:] if row.get("role") == "assistant")
        log = getattr(self.agents.conversation.event_emitter, "event_log", None)
        offers = log.query(user_id=user_id, event_type=EventType.AGENT_COMMUNICATION_OFFERED.value, limit=12) if log else []
        return {"pending_offers": self.pending_communications(user_id), "recent_offers": [{"occurred_at": row["occurred_at"], **{key: value for key, value in row["payload"].items() if key != "presentation"}} for row in offers], "recent_assistant_messages": recent[-12:]}

    def pending_communications(self, user_id):
        result = []
        ambient = self.agents.conversation.ambient_service
        for task in self.tasks.execution_tasks(run_type="ambient"):
            if task["user_id"] != user_id:
                continue
            try:
                if ambient is None or ambient.descendant_authority(task) is None:
                    continue
            except PermissionError:
                continue
            for run in task["runs"]:
                for row in run["metadata"].get("agent_outbox", []):
                    try:
                        notice = UserNotice.model_validate(row)
                    except ValueError:
                        continue
                    if not notice.received:
                        result.append({**notice.model_dump(), "task_id": task["task_id"], "run_id": run["run_id"]})
        return result[-12:]

    def defer_communication(self, context, *, session_id, content, delivery_id):
        self.tasks.append_agent_message(task_id=context.task_id, user_id=context.user_id, run_id=context.task_run_id, token=context.execution_token, message={"message_id": delivery_id, "kind": "user-notice", "session_id": session_id, "content": content, "received": False})

    def cached_presentation(self, user_id, *, visit_id, language):
        log = getattr(self.agents.conversation.event_emitter, "event_log", None)
        if log is None:
            return None
        for row in reversed(log.query(user_id=user_id, event_type=EventType.AGENT_COMMUNICATION_OFFERED.value, limit=24)):
            presentation = row["payload"].get("presentation") or {}
            if row["payload"].get("kind") == "welcome" and presentation.get("visit_id") == visit_id[:200] and presentation.get("language") == language:
                return presentation.get("response")
        return None

    def communication_admission(self, user_id, content, *, delivery_id):
        recent = self.communication_context(user_id)
        normalized = " ".join(content.split())
        for row in recent["recent_assistant_messages"]:
            if " ".join(row["content"].split()) == normalized:
                return {"allowed": False, "status": "already_communicated", "reason": "the same content is already in owned conversation history"}
        for row in reversed(recent["recent_offers"]):
            if row.get("delivery_id") == delivery_id:
                return {"allowed": False, "status": "already_communicated", "reason": "delivery receipt already exists"}
            if " ".join(str(row.get("content") or "").split()) == normalized:
                return {"allowed": False, "status": "already_communicated", "reason": "the same content was already offered"}
            offered = datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00")).timestamp()
            remaining = config.ambient.communication_cooldown_s - (time.time() - offered)
            if remaining > 0:
                return {"allowed": False, "status": "deferred", "retry_after_s": remaining, "reason": "recent communication; retain the finding and choose a quieter channel or a later activation"}
        return {"allowed": True}

    async def record_communication(self, *, user_id, session_id, kind, content, delivery_id, payload=None):
        emitter = self.agents.conversation.event_emitter
        if emitter is not None:
            await emitter.emit(EventType.AGENT_COMMUNICATION_OFFERED, {"user_id": user_id, "session_id": session_id, "kind": kind, "content": content, "delivery_id": delivery_id, "presentation": payload or {}})

    def _entry(self, task, run, *, kind, content, delivery, message_id=None, outcome=None):
        descriptor = self.agents._descriptor(task)
        return AgentMessage(
            message_id=message_id or f"agent_msg_{uuid4().hex}", kind=kind,
            sender_task_id=task["task_id"], sender_run_id=run["run_id"],
            recipient_task_id=descriptor.get("parent_agent_task_id"),
            session_id=descriptor["parent_session_id"], delivery=delivery,
            content=content, outcome=outcome,
            created_at=run.get("ended_at") or datetime.now(timezone.utc).isoformat(),
        ).model_dump()

    def report(self, request, *, sender):
        scope = current_delegation()
        if scope is None or scope.closed or scope.budget.closed or not scope.agent_task_id:
            raise PermissionError("only a live persistent child can report")
        if sender.task_id != scope.agent_task_id:
            raise PermissionError("reporter does not match the active child")
        task = self.tasks.get_task(sender.task_id, user_id=sender.user_id)
        if task is None:
            raise PermissionError("child does not exist")
        token = sender.execution_token
        if self.agents.runtime._tokens.get(sender.task_run_id) != token:
            raise PermissionError("reporter is not the current resident execution")
        self.tasks.assert_execution(task_id=sender.task_id, user_id=sender.user_id, token=token)
        run = next(row for row in task["runs"] if row["run_id"] == sender.task_run_id)
        if run["status"] != "running" or task["status"] in {"paused", "cancelled"}:
            raise PermissionError("child is not running")
        descriptor = self.agents._descriptor(task)
        pending = self.pending(user_id=sender.user_id, session_id=descriptor["parent_session_id"], agent_task_id=descriptor.get("parent_agent_task_id"))
        if len(pending) >= config.multi_agent.max_pending:
            raise ValueError("parent inbox is full")
        entry = self._entry(task, run, kind="subagent-report", content=request.content[:config.multi_agent.result_chars], delivery=request.delivery)
        accepted = self.tasks.append_agent_message(task_id=task["task_id"], user_id=task["user_id"], run_id=run["run_id"], message=entry, token=token)
        return {"status": "accepted", "message_id": accepted["message_id"], "delivery": request.delivery}

    def _rows(self):
        for task in self.tasks.execution_tasks(run_type="subagent"):
            try:
                descriptor = self.agents._descriptor(task)
            except ValueError:
                continue
            for run in task["runs"]:
                for value in run["metadata"].get("agent_outbox", []):
                    try:
                        row = AgentMessage.model_validate(value).model_dump()
                    except ValueError:
                        continue
                    # Imported data cannot redirect a report away from durable lineage.
                    if (row["sender_task_id"] == task["task_id"] and row["sender_run_id"] == run["run_id"]
                            and row["session_id"] == descriptor["parent_session_id"]
                            and row["recipient_task_id"] == descriptor.get("parent_agent_task_id")):
                        if row["kind"] == "subagent-settled" and (row["outcome"] != run["status"] or row["message_id"] != f"agent_settled:{task['task_id']}:{run['run_id']}"):
                            continue
                        if row["kind"] == "subagent-report" and row["outcome"] is not None:
                            continue
                        yield task, row

    def pending(self, *, user_id, session_id, agent_task_id=None):
        return sorted([
            row for task, row in self._rows()
            if task["user_id"] == user_id and not row["received"]
            and (session_id is None or row["session_id"] == session_id) and row["recipient_task_id"] == agent_task_id
        ], key=lambda row: (row["created_at"], row["message_id"]))

    def project(self, context, messages, user_config=None):
        scope = current_delegation()
        address = scope.agent_task_id if scope is not None else None
        rows = self.pending(user_id=context.user_id, session_id=context.session_id if scope is not None and scope.depth else None, agent_task_id=address)
        # An explicit per-step batch prevents repeated full status dumps and separates
        # Runtime lifecycle facts from child-authored text at user trust level.
        messages = [row for row in messages if not (row.get("role") == "user" and str(row.get("content") or "").startswith(MESSAGE_PREFIX))]
        if rows:
            policy = ActionConfig(**{**config.action.model_dump(), **((user_config or {}).get("action") or {})})
            remaining = policy.observation_history_chars
            batch = []
            for row in rows[:config.multi_agent.max_pending]:
                text = row["content"][:min(policy.observation_chars, remaining)]
                batch.append({**row, "content": text})
                remaining -= len(text) + 400
                if remaining <= 0:
                    break
            context.agent_message_ids = sorted(set(getattr(context, "agent_message_ids", [])) | {row["message_id"] for row in batch})
            payload = [{key: row[key] for key in ("message_id", "kind", "sender_task_id", "sender_run_id", "outcome", "content")} for row in batch]
            messages.append({"role": "user", "content": MESSAGE_PREFIX + json.dumps(payload, ensure_ascii=False)})
        return messages

    def _settlements(self):
        eligible = []
        for task in self.tasks.execution_tasks(run_type="subagent"):
            try:
                descriptor = self.agents._descriptor(task)
            except ValueError:
                continue
            eligible.append((task, descriptor))
        # Children first: their pending settlement must reach a parent before that
        # parent can be considered quiescent. Queued turns settle as one batch.
        for task, descriptor in sorted(eligible, key=lambda pair: pair[1]["depth"], reverse=True):
            if task["status"] != "cancelled":
                if task["status"] == "paused" or any(run["status"] in {"pending", "running", "paused", "waiting_user", "waiting_human"} for run in task["runs"]):
                    continue
                children = [child for child, lineage in eligible if child["user_id"] == task["user_id"] and lineage.get("parent_agent_task_id") == task["task_id"]]
                if any(run["status"] in {"pending", "running"} for child in children for run in child["runs"]):
                    continue
                if any(row["delivery"] == "wakeup" for row in self.pending(user_id=task["user_id"], session_id=descriptor["parent_session_id"], agent_task_id=task["task_id"])):
                    continue
            terminal = [run for run in task["runs"] if run["status"] in {"completed", "failed", "cancelled"}]
            for run in terminal[-1:]:
                mid = f"agent_settled:{task['task_id']}:{run['run_id']}"
                if any(row.get("message_id") == mid for row in run["metadata"].get("agent_outbox", [])):
                    continue
                # Reconstructed from committed state after restart; never a model claim.
                content = str(run["metadata"].get("output") or run["metadata"].get("error") or "")[:config.multi_agent.result_chars]
                entry = self._entry(task, run, kind="subagent-settled", content=content, delivery="wakeup", message_id=mid, outcome=run["status"])
                self.tasks.append_agent_message(task_id=task["task_id"], user_id=task["user_id"], run_id=run["run_id"], message=entry)

    def _receipts(self):
        manager = self.agents.conversation.message_manager
        by_user = defaultdict(set)
        for task, row in self._rows():
            if row["received"]:
                continue
            address = row["recipient_task_id"]
            if address:
                recipient = self.tasks.get_task(address, user_id=task["user_id"])
                receipts = {mid for run in (recipient or {}).get("runs", []) if run["status"] == "completed" for mid in run["metadata"].get("agent_message_ids", [])}
            elif manager is not None:
                receipts = manager.agent_message_receipts(None, user_id=task["user_id"])
            else:
                receipts = set()
            if row["message_id"] in receipts:
                by_user[task["user_id"]].add(row["message_id"])
        for user, ids in by_user.items():
            self.tasks.acknowledge_agent_messages(user_id=user, message_ids=list(ids))
        if manager is not None:
            for user in {task["user_id"] for task in self.tasks.execution_tasks(run_type="ambient")}:
                committed = manager.agent_message_receipts(None, user_id=user)
                ids = [row["message_id"] for row in self.pending_communications(user) if row["message_id"] in committed]
                if ids:
                    self.tasks.acknowledge_agent_messages(user_id=user, message_ids=ids)

    def recover(self):
        """Called by the existing TaskRuntime supervisor, including cold startup."""
        self._settlements()
        self._receipts()
        if self.agents.runtime._shutting_down:
            return
        groups = defaultdict(list)
        for task, row in self._rows():
            if not row["received"] and row["delivery"] == "wakeup":
                groups[(task["user_id"], row["session_id"] if row["recipient_task_id"] else None, row["recipient_task_id"])].append((task, row))
        for (user, session, address), entries in groups.items():
            if not config.multi_agent.enabled or not self.agents._config(user).get("multi_agent", {}).get("enabled", True):
                continue
            if self.agents.conversation.agent_is_active(user, session, address):
                continue
            if address:
                target = self.tasks.get_task(address, user_id=user)
                if target is None or target["status"] in {"paused", "cancelled"}:
                    continue
                if target.get("source") == "ambient":
                    ambient = self.agents.conversation.ambient_service
                    if ambient is not None:
                        try:
                            ambient.wake_for_reports(target, sorted(row["message_id"] for _, row in entries))
                        except PermissionError:
                            pass
                    continue
                run_type = "subagent"
            else:
                manager = self.agents.conversation.message_manager
                session = entries[-1][1]["session_id"]
                session_info = manager.get_session(session, user_id=user) if manager is not None else None
                if not session_info or manager.has_active_user_turn(user):
                    continue
                target = next((item for item in self.tasks.execution_tasks(run_type=INBOX_RUN_TYPE) if item["user_id"] == user), None)
                if target and target["status"] in {"paused", "cancelled"}:
                    continue
                run_type = INBOX_RUN_TYPE
            if target and any(run["status"] in {"pending", "running", "paused", "waiting_user", "waiting_human"} for run in target["runs"]):
                continue
            ids = sorted(row["message_id"] for _, row in entries)
            run_id = "agent_delivery_" + sha256("\n".join(ids).encode()).hexdigest()[:32]
            metadata = {"message": "", "message_source": "agent_inbox", "agent_message_ids": ids}
            if target is None:
                origin = entries[0][0]
                target = self.tasks.create_task(
                    user_id=user, session_id=session, title=session_info.get("title") or origin["title"], source="agent_inbox",
                    metadata={"continuable": True, "delegation": self.agents._descriptor(origin)},
                    initial_run={"run_id": run_id, "run_type": run_type, "metadata": metadata},
                )
            else:
                # A failed delivery remains inspectable; only explicit retry/resume or
                # a genuinely new message may start another attempt.
                if any(run["run_id"] == run_id for run in target["runs"]):
                    continue
                self.tasks.start_run(task_id=target["task_id"], user_id=user, run_id=run_id, run_type=run_type, session_id=session, status="pending", metadata=metadata)

