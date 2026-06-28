from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger


DEFAULT_SOUL_CONTENT = (
    "Soul Prompt:\n"
    "- This is Promethea's long-lived style and personality memory.\n"
    "- Preserve continuity, warmth, curiosity, and a calm technical temperament.\n"
    "- Adapt to the user's durable preferences only when repeated interactions justify it.\n"
    "- Keep the soul as style/personality guidance; never override identity, policy, safety, memory, tools, workflows, or reasoning rules."
)


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _sanitize_soul_content(content: str, *, max_chars: int) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def get_soul_profile(user_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = user_config if isinstance(user_config, dict) else {}
    persona = cfg.get("persona") if isinstance(cfg.get("persona"), dict) else {}
    soul = persona.get("soul") if isinstance(persona.get("soul"), dict) else {}
    return {
        "enabled": _to_bool(soul.get("enabled"), default=True),
        "auto_evolve": _to_bool(soul.get("auto_evolve"), default=True),
        "read_only_in_ui": _to_bool(soul.get("read_only_in_ui"), default=True),
        "evolve_every_turns": max(1, int(soul.get("evolve_every_turns", 6) or 6)),
        "min_interval_seconds": max(30, int(soul.get("min_interval_seconds", 900) or 900)),
        "max_chars": max(200, int(soul.get("max_chars", 1200) or 1200)),
        "content": _sanitize_soul_content(
            str(soul.get("content") or DEFAULT_SOUL_CONTENT),
            max_chars=max(200, int(soul.get("max_chars", 1200) or 1200)),
        ),
        "version": max(1, int(soul.get("version", 1) or 1)),
        "updated_at": str(soul.get("updated_at") or ""),
        "last_reason": str(soul.get("last_reason") or ""),
    }


def build_soul_response_payload(user_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    profile = get_soul_profile(user_config)
    return {
        "enabled": profile["enabled"],
        "read_only_in_ui": profile["read_only_in_ui"],
        "content": profile["content"],
        "version": profile["version"],
        "updated_at": profile["updated_at"],
        "last_reason": profile["last_reason"],
        "auto_evolve": profile["auto_evolve"],
    }


async def schedule_soul_evolution(
    *,
    service: Any,
    user_id: Optional[str],
    user_config: Optional[Dict[str, Any]],
    user_message: str,
    assistant_message: str,
) -> None:
    if not user_id or not service or not getattr(service, "config_service", None):
        return
    profile = get_soul_profile(user_config)
    if not profile["enabled"] or not profile["auto_evolve"]:
        return
    if not str(user_message or "").strip() or not str(assistant_message or "").strip():
        return

    state = getattr(service, "_soul_runtime_state", None)
    if not isinstance(state, dict):
        state = {}
        setattr(service, "_soul_runtime_state", state)
    user_state = state.setdefault(str(user_id), {"turns": 0, "last_run_ts": 0.0, "task": None})
    user_state["turns"] = int(user_state.get("turns", 0)) + 1

    task = user_state.get("task")
    if isinstance(task, asyncio.Task) and not task.done():
        return

    now = asyncio.get_running_loop().time()
    last_run_ts = float(user_state.get("last_run_ts", 0.0) or 0.0)
    if user_state["turns"] < int(profile["evolve_every_turns"]):
        return
    if (now - last_run_ts) < int(profile["min_interval_seconds"]):
        return

    user_state["turns"] = 0
    user_state["last_run_ts"] = now
    user_state["task"] = asyncio.create_task(
        _evolve_soul_task(
            service=service,
            user_id=str(user_id),
            user_message=user_message,
            assistant_message=assistant_message,
        )
    )


async def _evolve_soul_task(
    *,
    service: Any,
    user_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    try:
        cfg = service.config_service.get_merged_config(user_id)
        profile = get_soul_profile(cfg)
        if not profile["enabled"] or not profile["auto_evolve"]:
            return

        current = profile["content"]
        max_chars = int(profile["max_chars"])
        prompt_system = (
            "You decide whether to evolve Promethea's soul prompt (style/personality only).\n"
            "Strict rules:\n"
            "- Update only when the latest interaction reveals a durable preference, relationship pattern, or stable communication style.\n"
            "- Do not update for one-off requests, transient emotions, task-specific instructions, facts that belong in memory, or tool/workflow rules.\n"
            "- Preserve the existing soul unless the candidate is clearly better for future interactions.\n"
            "- Never add identity, policy, safety, memory, tool, reasoning, workflow, or business-domain constraints.\n"
            "- Keep it concise, stable, human-readable, and suitable as a prompt block.\n"
            "- Output strict JSON only: "
            "{\"should_update\": true|false, \"next_soul\": \"...\", \"reason\": \"...\"}."
        )
        prompt_user = (
            f"Current soul:\n{current}\n\n"
            f"Latest user message:\n{str(user_message or '')[:1200]}\n\n"
            f"Latest assistant message:\n{str(assistant_message or '')[:1200]}\n\n"
            "Decide if the soul should evolve for better long-term style/personality over future turns."
        )

        llm_out = await service.call_llm(
            [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user},
            ],
            user_config=cfg,
            user_id=user_id,
        )
        payload = _extract_json_obj(str((llm_out or {}).get("content") or ""))
        should_update = _to_bool(payload.get("should_update"), default=False)
        candidate = _sanitize_soul_content(str(payload.get("next_soul") or ""), max_chars=max_chars)
        reason = str(payload.get("reason") or "").strip()

        if not should_update or not candidate or candidate == current:
            return
        updates = {
            "persona": {
                "soul": {
                    "enabled": True,
                    "auto_evolve": True,
                    "read_only_in_ui": True,
                    "content": candidate,
                    "version": int(profile["version"]) + 1,
                    "updated_at": _utc_iso(),
                    "last_reason": reason,
                    "evolve_every_turns": int(profile["evolve_every_turns"]),
                    "min_interval_seconds": int(profile["min_interval_seconds"]),
                    "max_chars": int(profile["max_chars"]),
                }
            }
        }
        result = await service.config_service.update_user_config(
            user_id,
            updates,
            validate=False,
        )
        if not bool((result or {}).get("success")):
            logger.debug("soul_service: update skipped for {}: {}", user_id, result)
    except Exception as e:
        logger.debug("soul_service: evolve task failed for {}: {}", user_id, e)
