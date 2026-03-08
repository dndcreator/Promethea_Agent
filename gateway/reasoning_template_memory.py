from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from config import config as global_config


class ReasoningTemplateMemory:
    """
    Dedicated storage for reasoning templates.

    This module is intentionally separated from the general memory subsystem.
    It only stores successful reasoning paths/templates and lightweight
    optimization profiles for ToT-ReAct strategy reuse.
    """

    def __init__(self, base_dir: Optional[Path] = None, max_templates_per_user: int = 200) -> None:
        root = base_dir or (Path(global_config.system.log_dir) / "reasoning_templates")
        self.base_dir = Path(root)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.max_templates_per_user = max(20, int(max_templates_per_user))

    def match_template(self, *, user_id: str, task: str) -> Dict[str, Any]:
        templates = self._load_templates(user_id)
        if not templates:
            return {"matched": False, "score": 0.0, "template": None}
        task_tokens = self._tokenize(task)
        if not task_tokens:
            return {"matched": False, "score": 0.0, "template": None}

        best: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for item in templates:
            score = self._similarity(task_tokens, item.get("task_tokens", []))
            if score > best_score:
                best = item
                best_score = score
        if not best or best_score < 0.32:
            return {"matched": False, "score": best_score, "template": None}
        return {"matched": True, "score": best_score, "template": best}

    def get_strategy_hints(self, *, user_id: str) -> Dict[str, Any]:
        profile = self._load_profile(user_id)
        if not isinstance(profile, dict):
            return {}
        return {
            "template_count": int(profile.get("template_count", 0)),
            "max_steps_hint": int(profile.get("max_steps_hint", 0)),
            "branch_factor_hint": int(profile.get("branch_factor_hint", 0)),
            "beam_width_hint": int(profile.get("beam_width_hint", 0)),
            "memory_call_rate": float(profile.get("memory_call_rate", 0.0)),
            "tool_call_rate": float(profile.get("tool_call_rate", 0.0)),
            "preferred_tools": profile.get("preferred_tools", []) or [],
        }

    def record_success(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        assistant_output: str,
        gate: Dict[str, Any],
        policy: Dict[str, Any],
        tree_payload: Dict[str, Any],
    ) -> None:
        try:
            template = self._build_template(
                user_id=user_id,
                session_id=session_id,
                user_message=user_message,
                assistant_output=assistant_output,
                gate=gate,
                policy=policy,
                tree_payload=tree_payload,
            )
            if not template.get("steps"):
                return
            self._append_success_path_log(user_id=user_id, payload={"template": template, "tree": tree_payload})
            self._upsert_template(user_id=user_id, template=template)
            self._recompute_profile(user_id=user_id)
        except Exception as e:
            logger.debug("ReasoningTemplateMemory: record_success failed: {}", e)

    def _build_template(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        assistant_output: str,
        gate: Dict[str, Any],
        policy: Dict[str, Any],
        tree_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        nodes = tree_payload.get("nodes", []) if isinstance(tree_payload, dict) else []
        steps: List[Dict[str, Any]] = []
        tools: List[Dict[str, str]] = []
        for node in nodes:
            kind = str(node.get("kind", "")).strip().lower()
            if kind == "thought":
                md = node.get("metadata") or {}
                if not isinstance(md, dict):
                    md = {}
                title = str(md.get("title") or node.get("title") or "thought step").strip()
                goal = str(md.get("goal") or title or "continue").strip()
                steps.append(
                    {
                        "title": title or "thought step",
                        "goal": goal or "continue",
                        "requires_memory": self._to_bool(md.get("requires_memory"), False),
                        "memory_query": str(md.get("memory_query", "")).strip(),
                        "requires_tools": self._to_bool(md.get("requires_tools"), False),
                        "tool_intent": str(md.get("tool_intent", "")).strip(),
                        "notes": str(md.get("notes", "")).strip(),
                    }
                )
            elif kind == "tool":
                md = node.get("metadata") or {}
                if isinstance(md, dict):
                    service_name = str(md.get("service_name", "")).strip()
                    tool_name = str(md.get("tool_name", "")).strip()
                    if service_name or tool_name:
                        tools.append(
                            {
                                "service_name": service_name,
                                "tool_name": tool_name,
                            }
                        )

        deduped_steps: List[Dict[str, Any]] = []
        seen_step_keys = set()
        for step in steps:
            key = (step["title"].lower(), step["goal"].lower())
            if key in seen_step_keys:
                continue
            seen_step_keys.add(key)
            deduped_steps.append(step)

        stats = tree_payload.get("stats", {}) if isinstance(tree_payload, dict) else {}
        return {
            "template_id": uuid.uuid4().hex,
            "user_id": user_id,
            "session_id": session_id,
            "created_at": time.time(),
            "last_used_at": time.time(),
            "success_count": 1,
            "task": user_message,
            "task_tokens": self._tokenize(user_message),
            "assistant_preview": (assistant_output or "")[:300],
            "gate": gate if isinstance(gate, dict) else {},
            "policy_snapshot": policy if isinstance(policy, dict) else {},
            "steps": deduped_steps[:20],
            "tools": tools[:20],
            "stats": {
                "iterations": int(stats.get("iterations", 0) or 0),
                "memory_calls": int(stats.get("memory_calls", 0) or 0),
                "tool_calls": int(stats.get("tool_calls", 0) or 0),
                "think_calls": int(stats.get("think_calls", 0) or 0),
            },
        }

    def _upsert_template(self, *, user_id: str, template: Dict[str, Any]) -> None:
        templates = self._load_templates(user_id)
        incoming_tokens = template.get("task_tokens", []) or []
        merged = False
        for item in templates:
            score = self._similarity(incoming_tokens, item.get("task_tokens", []) or [])
            if score >= 0.75:
                item["success_count"] = int(item.get("success_count", 0) or 0) + 1
                item["last_used_at"] = time.time()
                if len(template.get("steps", [])) >= len(item.get("steps", [])):
                    item["steps"] = template.get("steps", [])
                if template.get("tools"):
                    item["tools"] = template.get("tools", [])
                item["assistant_preview"] = template.get("assistant_preview", "")
                item["policy_snapshot"] = template.get("policy_snapshot", {})
                item["stats"] = template.get("stats", {})
                merged = True
                break
        if not merged:
            templates.append(template)

        templates.sort(
            key=lambda x: (
                int(x.get("success_count", 0) or 0),
                float(x.get("last_used_at", 0.0) or 0.0),
            ),
            reverse=True,
        )
        templates = templates[: self.max_templates_per_user]
        self._save_json(self._templates_path(user_id), {"templates": templates})

    def _recompute_profile(self, *, user_id: str) -> None:
        templates = self._load_templates(user_id)
        if not templates:
            self._save_json(self._profile_path(user_id), {"template_count": 0, "updated_at": time.time()})
            return

        total = len(templates)
        avg_steps = sum(len(item.get("steps", [])) for item in templates) / max(1, total)
        avg_iterations = sum(int(item.get("stats", {}).get("iterations", 0) or 0) for item in templates) / max(1, total)
        avg_memory_calls = sum(int(item.get("stats", {}).get("memory_calls", 0) or 0) for item in templates) / max(1, total)
        avg_tool_calls = sum(int(item.get("stats", {}).get("tool_calls", 0) or 0) for item in templates) / max(1, total)
        memory_call_rate = avg_memory_calls / max(1.0, avg_iterations)
        tool_call_rate = avg_tool_calls / max(1.0, avg_iterations)

        tool_counter: Dict[str, int] = {}
        for item in templates:
            for tool in item.get("tools", []) or []:
                service = str(tool.get("service_name", "")).strip()
                tool_name = str(tool.get("tool_name", "")).strip()
                if not service and not tool_name:
                    continue
                key = f"{service}:{tool_name}"
                tool_counter[key] = tool_counter.get(key, 0) + 1
        preferred_tools = []
        for key, count in sorted(tool_counter.items(), key=lambda kv: kv[1], reverse=True)[:3]:
            service, tool_name = key.split(":", 1)
            preferred_tools.append({"service_name": service, "tool_name": tool_name, "count": count})

        profile = {
            "updated_at": time.time(),
            "template_count": total,
            "avg_steps": avg_steps,
            "avg_iterations": avg_iterations,
            "memory_call_rate": memory_call_rate,
            "tool_call_rate": tool_call_rate,
            # Lightweight OPRO-like policy hints computed from successful traces.
            "max_steps_hint": max(1, min(10, int(round(avg_steps)))),
            "branch_factor_hint": max(1, min(8, int(round(avg_steps / 2.0)))),
            "beam_width_hint": max(1, min(6, int(round(max(1.0, avg_steps / 3.0))))),
            "preferred_tools": preferred_tools,
        }
        self._save_json(self._profile_path(user_id), profile)

    def _append_success_path_log(self, *, user_id: str, payload: Dict[str, Any]) -> None:
        path = self._paths_log_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"timestamp": time.time(), **payload}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    def _load_templates(self, user_id: str) -> List[Dict[str, Any]]:
        data = self._load_json(self._templates_path(user_id))
        templates = data.get("templates", []) if isinstance(data, dict) else []
        return templates if isinstance(templates, list) else []

    def _load_profile(self, user_id: str) -> Dict[str, Any]:
        data = self._load_json(self._profile_path(user_id))
        return data if isinstance(data, dict) else {}

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _templates_path(self, user_id: str) -> Path:
        return self.base_dir / f"{self._safe_user_segment(user_id)}.templates.json"

    def _profile_path(self, user_id: str) -> Path:
        return self.base_dir / f"{self._safe_user_segment(user_id)}.opro.json"

    def _paths_log_path(self, user_id: str) -> Path:
        return self.base_dir / f"{self._safe_user_segment(user_id)}.paths.jsonl"

    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
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
            if lowered in {"false", "0", "no", "n", "off", ""}:
                return False
        return bool(value)

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", (text or "").lower())
        # Keep small, deterministic token bag.
        uniq: List[str] = []
        seen = set()
        for tok in tokens:
            if tok in seen:
                continue
            seen.add(tok)
            uniq.append(tok)
            if len(uniq) >= 64:
                break
        return uniq

    @staticmethod
    def _similarity(tokens_a: List[str], tokens_b: List[str]) -> float:
        set_a = set(tokens_a or [])
        set_b = set(tokens_b or [])
        if not set_a or not set_b:
            return 0.0
        inter = len(set_a & set_b)
        union = len(set_a | set_b)
        if union == 0:
            return 0.0
        return inter / union

    @staticmethod
    def _safe_user_segment(user_id: Optional[str]) -> str:
        uid = str(user_id or "default_user").strip() or "default_user"
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in uid)
        return safe[:128] or "default_user"
