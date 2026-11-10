"""Observation-source contract; scheduling and delivery remain Temporal's responsibility."""
from typing import Any
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from agentkit.mcp.tool_result import normalize_tool_result


class SourceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=500)
    data: dict[str, Any]
    references: list[str] = Field(default_factory=list, max_length=20)


class SourceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    observations: list[SourceObservation] = Field(max_length=100)
    cursor: dict[str, Any] = Field(default_factory=dict)


def stage_observations(job, result):
    normalized = normalize_tool_result(job["target"]["tool_name"], result)
    if not normalized.ok:
        raise RuntimeError("observation source failed; cursor not advanced")
    batch = SourceBatch.model_validate(normalized.value)
    if len(json.dumps(batch.model_dump(), ensure_ascii=False, allow_nan=False).encode()) > 256000:
        raise ValueError("observation batch exceeds 256KB; retain large evidence at its source")
    seen = dict(job.get("observed_versions") or {})
    pending, keys = [], set()
    for item in batch.observations:
        if item.key in keys:
            raise ValueError("observation batch contains duplicate object keys")
        keys.add(item.key)
        if seen.get(item.key) == item.version:
            continue
        identity = json.dumps([job["job_id"], item.key, item.version], ensure_ascii=False)
        identifier = "source_" + hashlib.sha256(identity.encode()).hexdigest()
        context = job["execution_context"]
        pending.append({"idempotency_key": identifier, "payload": {
            "user_id": context["user_id"], "session_id": context.get("session_id") or None,
            "source": job["target"]["service_name"] + "." + job["target"]["tool_name"],
            "source_job_id": job["job_id"], "source_event_key": identifier,
            "object_key": item.key, "version": item.version,
            "data": item.data, "references": item.references,
        }})
        seen.pop(item.key, None)
        seen[item.key] = item.version
    return {"observation_cursor": batch.cursor, "observed_versions": dict(list(seen.items())[-4096:]), "pending_observations": pending}
