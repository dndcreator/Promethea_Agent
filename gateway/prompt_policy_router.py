from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, Optional

from loguru import logger


DEFAULT_PROMPT_POLICY: Dict[str, Any] = {
    "source": "default",
    "mode": "fast",
    "cognitive_mode": "direct",
    "reasoning_budget": "none",
    "tool_budget": 0,
    "memory_budget": "brief",
    "need_user_visible_reasoning": False,
    "need_memory": None,
    "need_reasoning": False,
    "need_tools": False,
    "need_workspace": False,
    "need_org_context": False,
    "action_intent": "none",
    "confidence": 0.5,
    "reason": "fallback_default",
}


class PromptPolicyRouter:
    """
    LLM-driven first-pass router for dynamic prompt blocks.

    Core blocks such as identity, soul, and policy safety are still enforced by
    code in PromptAssembler. This router does not use keyword lists or
    deterministic memory hints; it only normalizes the model's routing decision
    and falls back to a neutral default if routing fails.
    """

    SYSTEM_BLOCK = (
        "You are Promethea's prompt policy router.\n"
        "Your job is not to answer the user. Decide which dynamic prompt blocks "
        "the runtime should prepare before the real answer.\n"
        "Core identity, soul, and safety policy are always enforced "
        "by code; do not try to disable or rewrite them.\n"
        "Return strict JSON only with keys: cognitive_mode, mode, reasoning_budget, "
        "tool_budget, memory_budget, need_user_visible_reasoning, need_memory, "
        "need_reasoning, need_tools, need_workspace, need_org_context, action_intent, reason, confidence.\n"
        "cognitive_mode must be one of: direct, light_action, deep_reasoning, workflow.\n"
        "mode is the legacy executor mode and must be one of: fast, deep, workflow.\n"
        "Use direct for ordinary answers that do not need external action or a visible reasoning tree.\n"
        "Use light_action for simple external actions such as current lookup, exact calculation, "
        "simple search, or one-shot file/workspace operations. Keep reasoning_budget none or small.\n"
        "Use deep_reasoning only when the task needs multi-step investigation, planning, comparison, "
        "debugging, design, research synthesis, or the user explicitly asks for substantial analysis.\n"
        "If the user asks to 'think' but the task itself is simple, prefer light_action or direct.\n"
        "Use workflow only for explicit long-running workflow orchestration.\n"
        "reasoning_budget must be none, small, or large. Only large should start the full reasoning tree.\n"
        "tool_budget should be 0 for direct, usually 1-2 for light_action, and 3-5 for deep_reasoning/workflow.\n"
        "memory_budget must be none, brief, or full.\n"
        "Use need_memory when long-term personal context, prior user state, user identity, "
        "user preferences, or cross-turn facts may matter.\n"
        "Use need_reasoning only when the full reasoning tree is worth its latency.\n"
        "Use need_tools when external actions, files, web, code execution, or automation may be needed.\n"
        "action_intent must be one of: none, external_read, external_write, external_action. "
        "Set it whenever completing the user's request depends on runtime evidence or an external side effect, "
        "even when no currently callable tool can satisfy the request.\n"
        "When a runtime registered-tools snapshot is provided, treat it as the source of truth for what this Promethea deployment can do.\n"
        "Only tools with callable_now=true can be invoked in this turn. Distinguish unavailable registered tools from tools that are absent.\n"
        "Use the recent conversation to resolve short follow-ups such as 'then AI', 'that one', or 'continue'.\n"
        "Current/latest/recent external facts require tools unless the user explicitly asks for a non-current general explanation.\n"
        "For news requests, prefer a news-specific search tool when one is present in the runtime catalog."
    )

    @staticmethod
    def _to_bool(value: Any, default: Optional[bool] = False) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y", "on"}:
                return True
            if lowered in {"false", "0", "no", "n", "off"}:
                return False
            if lowered in {"unknown", "null", "none", ""}:
                return default
        return default

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S | re.I)
        if fenced:
            try:
                parsed = json.loads(fenced.group(1))
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    @classmethod
    def _normalize_policy(cls, payload: Dict[str, Any], *, source: str) -> Dict[str, Any]:
        policy = dict(DEFAULT_PROMPT_POLICY)
        policy["source"] = source
        raw_mode = str(payload.get("cognitive_mode") or payload.get("mode") or "").strip().lower()
        aliases = {
            "fast": "direct",
            "deep": "deep_reasoning",
            "reasoning": "deep_reasoning",
            "light": "light_action",
            "tool": "light_action",
            "tools": "light_action",
        }
        cognitive_mode = aliases.get(raw_mode, raw_mode or policy["cognitive_mode"])
        if cognitive_mode not in {"direct", "light_action", "deep_reasoning", "workflow"}:
            cognitive_mode = "direct"
        action_intent = str(payload.get("action_intent") or "none").strip().lower()
        if action_intent not in {"none", "external_read", "external_write", "external_action"}:
            action_intent = "none"
        policy["action_intent"] = action_intent
        if action_intent != "none" and cognitive_mode == "direct":
            cognitive_mode = "light_action"
        policy["cognitive_mode"] = cognitive_mode

        mode = str(payload.get("mode") or policy["mode"]).strip().lower()
        if mode not in {"fast", "deep", "workflow"}:
            mode = {
                "direct": "fast",
                "light_action": "fast",
                "deep_reasoning": "deep",
                "workflow": "workflow",
            }[cognitive_mode]
        if cognitive_mode in {"direct", "light_action"} and mode not in {"fast"}:
            mode = "fast"
        if cognitive_mode == "deep_reasoning":
            mode = "deep"
        if cognitive_mode == "workflow":
            mode = "workflow"
        policy["mode"] = mode

        reasoning_budget = str(payload.get("reasoning_budget") or "").strip().lower()
        if reasoning_budget not in {"none", "small", "large"}:
            reasoning_budget = "large" if cognitive_mode in {"deep_reasoning", "workflow"} else "none"
        if cognitive_mode in {"direct", "light_action"} and reasoning_budget == "large":
            reasoning_budget = "small" if cognitive_mode == "light_action" else "none"
        if cognitive_mode in {"deep_reasoning", "workflow"}:
            reasoning_budget = "large"
        policy["reasoning_budget"] = reasoning_budget

        memory_budget = str(payload.get("memory_budget") or "").strip().lower()
        if memory_budget not in {"none", "brief", "full"}:
            memory_budget = "full" if cognitive_mode in {"deep_reasoning", "workflow"} else "brief"
        policy["memory_budget"] = memory_budget

        policy["need_memory"] = cls._to_bool(payload.get("need_memory"), default=None)
        policy["need_reasoning"] = reasoning_budget == "large" or bool(
            cls._to_bool(payload.get("need_reasoning"), default=False)
            and cognitive_mode in {"deep_reasoning", "workflow"}
        )
        policy["need_tools"] = bool(cls._to_bool(payload.get("need_tools"), default=False))
        if action_intent != "none":
            policy["need_tools"] = True
        if policy["need_tools"] and cognitive_mode == "direct":
            cognitive_mode = "light_action"
            policy["cognitive_mode"] = cognitive_mode
        policy["need_workspace"] = bool(cls._to_bool(payload.get("need_workspace"), default=False))
        policy["need_org_context"] = bool(cls._to_bool(payload.get("need_org_context"), default=False))
        try:
            requested_tool_budget = int(payload.get("tool_budget", policy["tool_budget"]))
        except Exception:
            requested_tool_budget = int(policy["tool_budget"])
        default_tool_budget = {
            "direct": 0,
            "light_action": 3,
            "deep_reasoning": 5,
            "workflow": 5,
        }[cognitive_mode]
        if requested_tool_budget <= 0 and policy["need_tools"]:
            requested_tool_budget = default_tool_budget
        if cognitive_mode == "light_action" and policy["need_tools"]:
            # One primary action, one verification/correction, and one recovery
            # step for normal external-source failures such as blocked search.
            requested_tool_budget = max(3, requested_tool_budget)
        max_budget = 8 if cognitive_mode in {"deep_reasoning", "workflow"} else 3
        if cognitive_mode == "direct" and not policy["need_tools"]:
            max_budget = 0
        policy["tool_budget"] = max(0, min(max_budget, requested_tool_budget))
        if policy["tool_budget"] > 0:
            policy["need_tools"] = True
        if policy["need_memory"] is False:
            policy["memory_budget"] = "none"
        elif policy["need_memory"] is True and policy["memory_budget"] == "none":
            policy["memory_budget"] = "brief"
        policy["need_user_visible_reasoning"] = bool(
            cls._to_bool(payload.get("need_user_visible_reasoning"), default=False)
        ) and policy["reasoning_budget"] == "large"
        policy["reason"] = str(payload.get("reason") or policy["reason"])[:300]
        try:
            policy["confidence"] = max(0.0, min(1.0, float(payload.get("confidence", policy["confidence"]))))
        except Exception:
            policy["confidence"] = 0.5
        return policy

    @classmethod
    def normalize_policy(cls, payload: Dict[str, Any], *, source: str = "normalized") -> Dict[str, Any]:
        return cls._normalize_policy(payload if isinstance(payload, dict) else {}, source=source)

    async def route(
        self,
        *,
        conversation_core: Any,
        user_message: str,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
        base_system_prompt: str = "",
        tool_catalog: Optional[Iterable[Dict[str, Any]]] = None,
        runtime_context: str = "",
        recent_messages: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        user_text = str(user_message or "").strip()
        if not user_text:
            return dict(DEFAULT_PROMPT_POLICY)

        try:
            call_llm = getattr(conversation_core, "call_llm", None)
            if not callable(call_llm):
                return dict(DEFAULT_PROMPT_POLICY)
            recent_text = self._format_recent_messages(recent_messages)
            response = await call_llm(
                [
                    {"role": "system", "content": self.SYSTEM_BLOCK},
                    {
                        "role": "user",
                        "content": (
                            "Base identity summary:\n"
                            f"{str(base_system_prompt or '')[:1200]}\n\n"
                            "Runtime registered tools (structured JSON):\n"
                            f"{self._format_tool_catalog(tool_catalog)}\n\n"
                            "Runtime context:\n"
                            f"{str(runtime_context or 'No runtime context was provided.')[:2500]}\n\n"
                            "Recent conversation:\n"
                            f"{recent_text or 'No recent conversation was provided.'}\n\n"
                            "User message:\n"
                            f"{user_text[:4000]}"
                        ),
                    },
                ],
                user_config=user_config,
                user_id=user_id,
            )
            if isinstance(response, dict) and response.get("status") == "error":
                return dict(DEFAULT_PROMPT_POLICY)
            payload = self._extract_json(str((response or {}).get("content") or ""))
            if not payload:
                return dict(DEFAULT_PROMPT_POLICY)
            routing_keys = {
                "cognitive_mode",
                "mode",
                "reasoning_budget",
                "tool_budget",
                "memory_budget",
                "need_memory",
                "need_reasoning",
                "need_tools",
                "need_workspace",
                "need_org_context",
                "action_intent",
            }
            if not any(key in payload for key in routing_keys):
                return dict(DEFAULT_PROMPT_POLICY)
            return self._normalize_policy(payload, source="llm")
        except Exception as e:
            logger.debug("PromptPolicyRouter: route fallback used: {}", e)
            return dict(DEFAULT_PROMPT_POLICY)

    @staticmethod
    def _format_recent_messages(recent_messages: Optional[Iterable[Dict[str, Any]]]) -> str:
        rows = []
        for message in list(recent_messages or [])[-6:]:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "unknown").strip() or "unknown"
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if len(content) > 700:
                content = content[:699].rstrip() + "..."
            rows.append(f"- {role}: {content}")
        return "\n".join(rows)

    @staticmethod
    def _format_tool_catalog(tool_catalog: Optional[Iterable[Dict[str, Any]]]) -> str:
        tools = [dict(item) for item in (tool_catalog or []) if isinstance(item, dict)]
        if not tools:
            return "[]"
        return json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
