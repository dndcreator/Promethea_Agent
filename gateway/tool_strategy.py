from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ToolCandidate:
    tool_type: str
    service_name: str
    tool_name: str
    score: float
    reasons: List[str]


class ToolStrategyEngine:
    """Deterministic tool routing helper to stabilize LLM tool selection."""

    def recommend(
        self,
        *,
        step: Dict[str, Any],
        user_message: str,
        observations: List[str],
        catalog: List[Dict[str, Any]],
        strategy_hints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not catalog:
            return {"use_tool": False, "candidates": []}

        text = " ".join(
            [
                str(user_message or ""),
                str(step.get("title", "")),
                str(step.get("goal", "")),
                str(step.get("tool_intent", "")),
                " ".join(str(x) for x in (observations or [])[-3:]),
            ]
        ).lower()

        preferred = []
        quality_map: Dict[str, Dict[str, Any]] = {}
        hints = strategy_hints or {}
        for item in hints.get("preferred_tools", []) or []:
            if isinstance(item, dict):
                preferred.append(
                    (
                        str(item.get("service_name", "")),
                        str(item.get("tool_name", "")),
                    )
                )
        for item in hints.get("tool_quality", []) or []:
            if not isinstance(item, dict):
                continue
            service_name = str(item.get("service_name", "")).strip()
            tool_name = str(item.get("tool_name", "")).strip()
            if not service_name and not tool_name:
                continue
            quality_map[f"{service_name}:{tool_name}"] = item

        scored: List[ToolCandidate] = []
        for entry in catalog:
            service = str(entry.get("service_name", ""))
            tool = str(entry.get("tool_name", ""))
            tool_type = str(entry.get("tool_type", "mcp"))
            desc = str(entry.get("description", "")).lower()
            full = f"{service}.{tool}".lower()

            score = 0.0
            reasons: List[str] = []

            overlap = 0
            for token in self._tokens(text):
                if token and (token in full or token in desc):
                    overlap += 1
            if overlap > 0:
                add = min(0.35, overlap * 0.03)
                score += add
                reasons.append(f"overlap+{add:.2f}")

            if any(k in text for k in ("browser", "url", "website", "click", "download page", "ui", "button", "on screen", "locate")):
                if service == "computer_control" and tool == "browser_action":
                    score += 0.40
                    reasons.append("browser_intent")
                if service == "computer_control" and tool == "perception_action":
                    score += 0.45
                    reasons.append("perception_intent")
            if any(k in text for k in ("open app", "launch", "process", "start client", "run command")):
                if service == "computer_control" and tool in {"process_action", "execute_command"}:
                    score += 0.35
                    reasons.append("process_intent")
            if any(k in text for k in ("folder", "directory", "path", "save", "file", "exists")):
                if service == "computer_control" and tool in {"fs_action", "read_file", "write_file", "list_files"}:
                    score += 0.30
                    reasons.append("filesystem_intent")
            if any(k in text for k in ("workflow", "resume", "checkpoint", "approval", "retry")):
                if service == "moirai":
                    score += 0.40
                    reasons.append("workflow_intent")
            if any(k in text for k in ("fetch", "web page", "pdf", "image", "ocr")):
                if service == "computer_control" and tool == "content_action":
                    score += 0.35
                    reasons.append("content_intent")
            if any(k in text for k in ("session", "agent", "plugin", "memory", "channel", "gateway status")):
                if service == "computer_control" and tool == "runtime_action":
                    score += 0.35
                    reasons.append("runtime_intent")
            if any(k in text for k in ("schedule", "cron", "job", "periodic", "recurring")):
                if service == "computer_control" and tool == "schedule_action":
                    score += 0.35
                    reasons.append("schedule_intent")
            if any(k in text for k in ("self evolve", "self-evolve", "self modify", "modify your code", "modify yourself", "self improvement", "agent evolves", "自我进化", "修改自己的代码")):
                if service == "self_evolve":
                    score += 0.55
                    reasons.append("self_evolve_intent")
            if any(k in text for k in ("graph", "node", "link", "relation", "depends on")):
                if service == "computer_control" and tool == "graph_action":
                    score += 0.35
                    reasons.append("graph_intent")

            if (service, tool) in preferred:
                score += 0.20
                reasons.append("historical_preference")

            if tool in {"delete_file", "execute_command"} and not any(
                k in text for k in ("delete", "remove", "run command", "execute")
            ):
                score -= 0.10
                reasons.append("risk_penalty")

            profile = quality_map.get(f"{service}:{tool}", {})
            score += self._quality_delta(profile=profile, reasons=reasons)
            score += self._risk_cost_delta(
                service_name=service,
                tool_name=tool,
                text=text,
                profile=profile,
                reasons=reasons,
            )

            scored.append(
                ToolCandidate(
                    tool_type=tool_type,
                    service_name=service,
                    tool_name=tool,
                    score=max(0.0, min(1.0, score)),
                    reasons=reasons,
                )
            )

        scored.sort(key=lambda c: c.score, reverse=True)
        top = scored[:5]
        best = top[0] if top else None
        if not best or best.score < 0.20:
            return {
                "use_tool": False,
                "confidence": best.score if best else 0.0,
                "candidates": [self._to_dict(c) for c in top],
            }
        return {
            "use_tool": True,
            "confidence": best.score,
            "tool_type": best.tool_type,
            "service_name": best.service_name,
            "tool_name": best.tool_name,
            "args": {},
            "why": ", ".join(best.reasons) or "best scored candidate",
            "candidates": [self._to_dict(c) for c in top],
        }

    @staticmethod
    def _tokens(text: str) -> List[str]:
        chars = []
        for ch in text:
            if ch.isalnum() or ch in {"_", "."}:
                chars.append(ch)
            else:
                chars.append(" ")
        return [x for x in "".join(chars).split() if len(x) >= 3]

    @staticmethod
    def _to_dict(c: ToolCandidate) -> Dict[str, Any]:
        return {
            "tool_type": c.tool_type,
            "service_name": c.service_name,
            "tool_name": c.tool_name,
            "score": c.score,
            "reasons": c.reasons,
        }

    @staticmethod
    def _quality_delta(*, profile: Dict[str, Any], reasons: List[str]) -> float:
        if not isinstance(profile, dict):
            return 0.0
        try:
            success_rate = float(profile.get("success_rate", 0.0))
        except Exception:
            success_rate = 0.0
        try:
            runs = int(profile.get("runs", 0))
        except Exception:
            runs = 0
        if runs < 3:
            return 0.0
        success_rate = max(0.0, min(1.0, success_rate))
        delta = (success_rate - 0.5) * 0.25
        if abs(delta) < 0.005:
            return 0.0
        reasons.append(f"quality_{'up' if delta >= 0 else 'down'}")
        return delta

    def _risk_cost_delta(
        self,
        *,
        service_name: str,
        tool_name: str,
        text: str,
        profile: Dict[str, Any],
        reasons: List[str],
    ) -> float:
        explicit_dangerous = any(
            k in text
            for k in (
                "delete",
                "remove",
                "terminate",
                "kill process",
                "execute command",
                "run command",
            )
        )
        risk_level = self._default_risk_level(service_name=service_name, tool_name=tool_name)
        cost_level = self._default_cost_level(service_name=service_name, tool_name=tool_name)

        if isinstance(profile, dict):
            risk_level = str(profile.get("risk_level", risk_level)).strip().lower() or risk_level
            cost_level = str(profile.get("cost_level", cost_level)).strip().lower() or cost_level

        delta = 0.0
        if not explicit_dangerous:
            risk_penalty = {"low": 0.0, "medium": -0.03, "high": -0.08}.get(risk_level, 0.0)
            if risk_penalty < 0:
                reasons.append(f"risk_{risk_level}")
                delta += risk_penalty

        cost_penalty = {"low": 0.0, "medium": -0.02, "high": -0.05}.get(cost_level, 0.0)
        if cost_penalty < 0:
            reasons.append(f"cost_{cost_level}")
            delta += cost_penalty

        return delta

    @staticmethod
    def _default_risk_level(*, service_name: str, tool_name: str) -> str:
        s = str(service_name).strip().lower()
        t = str(tool_name).strip().lower()
        if s == "computer_control" and t in {"process_action", "execute_command", "fs_action", "write_file", "delete_file"}:
            return "high"
        if s == "self_evolve":
            return "high"
        if s == "computer_control" and t in {"browser_action", "perception_action"}:
            return "medium"
        return "low"

    @staticmethod
    def _default_cost_level(*, service_name: str, tool_name: str) -> str:
        s = str(service_name).strip().lower()
        t = str(tool_name).strip().lower()
        if s == "computer_control" and t in {"perception_action", "content_action"}:
            return "high"
        if s == "computer_control" and t in {"browser_action", "process_action"}:
            return "medium"
        return "low"

