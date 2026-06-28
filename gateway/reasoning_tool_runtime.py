from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .reasoning_utils import to_bool


class ReasoningToolQualityTracker:
    """Small in-memory quality ledger for runtime tool selection hints."""

    def __init__(self) -> None:
        self._stats: Dict[str, Dict[str, Any]] = {}

    @property
    def stats(self) -> Dict[str, Dict[str, Any]]:
        return self._stats

    def record(
        self,
        *,
        service_name: str,
        tool_name: str,
        ok: bool,
        latency_ms: float,
    ) -> None:
        key = f"{service_name}:{tool_name}"
        row = self._stats.get(key)
        if not isinstance(row, dict):
            row = {
                "service_name": service_name,
                "tool_name": tool_name,
                "runs": 0,
                "ok": 0,
                "fail": 0,
                "avg_latency_ms": 0.0,
            }
            self._stats[key] = row

        row["runs"] = int(row.get("runs", 0)) + 1
        if ok:
            row["ok"] = int(row.get("ok", 0)) + 1
        else:
            row["fail"] = int(row.get("fail", 0)) + 1

        prev_avg = float(row.get("avg_latency_ms", 0.0) or 0.0)
        n = float(row["runs"])
        row["avg_latency_ms"] = max(0.0, ((prev_avg * (n - 1.0)) + max(0.0, float(latency_ms))) / n)

    def hints(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in self._stats.values():
            if not isinstance(item, dict):
                continue
            runs = max(1, int(item.get("runs", 0) or 0))
            ok = int(item.get("ok", 0) or 0)
            avg_latency = float(item.get("avg_latency_ms", 0.0) or 0.0)
            rows.append(
                {
                    "service_name": str(item.get("service_name", "") or ""),
                    "tool_name": str(item.get("tool_name", "") or ""),
                    "runs": runs,
                    "success_rate": ok / float(runs),
                    "avg_latency_ms": avg_latency,
                }
            )
        rows.sort(key=lambda x: (int(x.get("runs", 0)), float(x.get("success_rate", 0.0))), reverse=True)
        return rows[: max(1, int(limit))]


class ReasoningToolCatalogResolver:
    """Normalize LLM-selected tool identifiers against the runtime catalog."""

    def normalize_selected_tool(
        self,
        selected: Dict[str, Any],
        catalog: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(selected, dict):
            return {"use_tool": False}
        use_tool = to_bool(selected.get("use_tool"), default=False)
        service_name = str(selected.get("service_name") or "").strip()
        tool_name = str(selected.get("tool_name") or "").strip()
        if not use_tool or not tool_name:
            return {"use_tool": False}

        match = self.resolve_catalog_entry(catalog, service_name, tool_name)
        if not match:
            return {"use_tool": False}

        args = selected.get("args")
        if not isinstance(args, dict):
            args = {}
        return {
            "use_tool": True,
            "tool_type": match.get("tool_type") or selected.get("tool_type") or "mcp",
            "service_name": match.get("service_name") or service_name,
            "tool_name": match.get("tool_name") or tool_name,
            "args": args,
            "why": str(selected.get("why") or ""),
        }

    def resolve_catalog_entry(
        self,
        catalog: List[Dict[str, Any]],
        service_name: str,
        tool_name: str,
    ) -> Optional[Dict[str, Any]]:
        service = str(service_name or "").strip()
        tool = str(tool_name or "").strip()
        if not tool:
            return None

        exact = self.find_catalog_entry(catalog, service, tool)
        if exact:
            return exact

        normalized_service = self.normalize_tool_id(service)
        normalized_tool = self.normalize_tool_id(tool)
        candidates: List[tuple[float, Dict[str, Any]]] = []
        for item in catalog:
            item_service = str(item.get("service_name", "") or "").strip()
            item_tool = str(item.get("tool_name", "") or "").strip()
            if not item_tool:
                continue

            score = 0.0
            item_service_norm = self.normalize_tool_id(item_service)
            item_tool_norm = self.normalize_tool_id(item_tool)

            if tool and item_tool == tool:
                score += 10.0
            elif normalized_tool and item_tool_norm == normalized_tool:
                score += 8.0
            elif normalized_tool and normalized_tool in item_tool_norm:
                score += 4.0
            elif normalized_tool and item_tool_norm in normalized_tool:
                score += 2.0

            if service:
                if item_service == service:
                    score += 6.0
                elif normalized_service and item_service_norm == normalized_service:
                    score += 4.0
                elif normalized_service and normalized_service in item_service_norm:
                    score += 1.5

            if score > 0.0:
                candidates.append((score, item))

        if not candidates:
            return None
        candidates.sort(key=lambda row: row[0], reverse=True)
        best_score, best_item = candidates[0]
        if best_score < 7.0:
            return None
        return best_item

    @staticmethod
    def normalize_tool_id(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    @staticmethod
    def find_catalog_entry(
        catalog: List[Dict[str, Any]],
        service_name: str,
        tool_name: str,
    ) -> Optional[Dict[str, Any]]:
        if not tool_name:
            return None
        for item in catalog:
            item_service = str(item.get("service_name", "") or "")
            item_tool = str(item.get("tool_name", "") or "")
            if item_tool != tool_name:
                continue
            if service_name and item_service != service_name:
                continue
            return item
        return None
