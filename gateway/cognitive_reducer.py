"""Budgeted, query-conditioned cognition reduction over governed memory candidates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import time
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

LLMCall = Callable[[List[Dict[str, str]]], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class CognitiveRecallPolicy:
    enabled: bool = True
    candidate_pool_limit: int = 60
    fast_candidate_limit: int = 12
    fast_input_chars: int = 6000
    deep_candidate_threshold: int = 36
    max_channels: int = 3
    max_depth: int = 2
    max_parallel_calls: int = 4
    max_kernel_calls: int = 8
    kernel_input_chars: int = 16000
    max_skip_chars: int = 5000
    skip_score_threshold: float = 0.82
    deadline_ms: int = 6000

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]]) -> "CognitiveRecallPolicy":
        root = config if isinstance(config, dict) else {}
        self_model = root.get("self_model") if isinstance(root.get("self_model"), dict) else {}
        raw = self_model.get("recall") if isinstance(self_model.get("recall"), dict) else {}

        def integer(name: str, default: int, low: int, high: int) -> int:
            try:
                return max(low, min(high, int(raw.get(name, default))))
            except (TypeError, ValueError):
                return default

        def number(name: str, default: float, low: float, high: float) -> float:
            try:
                return max(low, min(high, float(raw.get(name, default))))
            except (TypeError, ValueError):
                return default

        return cls(
            enabled=bool(raw.get("enabled", True)),
            candidate_pool_limit=integer("candidate_pool_limit", 60, 4, 100),
            fast_candidate_limit=integer("fast_candidate_limit", 12, 1, 50),
            fast_input_chars=integer("fast_input_chars", 6000, 1000, 50000),
            deep_candidate_threshold=integer("deep_candidate_threshold", 36, 4, 100),
            max_channels=integer("max_channels", 3, 1, 5),
            max_depth=integer("max_depth", 2, 1, 3),
            max_parallel_calls=integer("max_parallel_calls", 4, 1, 12),
            max_kernel_calls=integer("max_kernel_calls", 8, 1, 24),
            kernel_input_chars=integer("kernel_input_chars", 16000, 2000, 60000),
            max_skip_chars=integer("max_skip_chars", 5000, 500, 20000),
            skip_score_threshold=number("skip_score_threshold", 0.82, 0.0, 1.0),
            deadline_ms=integer("deadline_ms", 6000, 250, 30000),
        )


class CognitiveReducer:
    """Produces an ephemeral CognitionSnapshot; it never persists memory."""

    def __init__(self, *, llm_call: Optional[LLMCall] = None) -> None:
        self.llm_call = llm_call

    @staticmethod
    def _item_chars(items: Iterable[Dict[str, Any]]) -> int:
        return sum(len(str(item.get("content") or "")) for item in items)

    @staticmethod
    def _skip_score(item: Dict[str, Any]) -> float:
        relevance = float(item.get("relevance_score") or 0.0)
        importance = float(item.get("importance") or 0.0)
        score = (relevance * 0.65) + (importance * 0.35)
        if item.get("action_required") or str(item.get("state") or "") == "uncertain":
            score += 0.18
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if metadata.get("conflict_flag") or metadata.get("supersedes") or metadata.get("superseded_by"):
            score += 0.18
        return max(0.0, min(1.0, score))

    @classmethod
    def _select_skip_buffer(
        cls,
        items: List[Dict[str, Any]],
        policy: CognitiveRecallPolicy,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        ranked = sorted(
            ((cls._skip_score(item), item) for item in items),
            key=lambda pair: pair[0],
            reverse=True,
        )
        selected: List[Dict[str, Any]] = []
        selected_ids: set[str] = set()
        used_chars = 0
        for score, item in ranked:
            is_governance_critical = bool(item.get("action_required")) or str(item.get("state") or "") == "uncertain"
            if score < policy.skip_score_threshold and not is_governance_critical:
                continue
            content = str(item.get("content") or "")
            if selected and used_chars + len(content) > policy.max_skip_chars:
                continue
            copied = dict(item)
            copied["skip_score"] = round(score, 4)
            selected.append(copied)
            selected_ids.add(str(item.get("cognition_id") or item.get("memory_id") or ""))
            used_chars += len(content)
        remaining = [
            item
            for item in items
            if str(item.get("cognition_id") or item.get("memory_id") or "") not in selected_ids
        ]
        return selected, remaining

    @staticmethod
    def _resolve_mode(
        requested_mode: str,
        items: List[Dict[str, Any]],
        policy: CognitiveRecallPolicy,
    ) -> str:
        requested = str(requested_mode or "auto").strip().lower()
        if requested in {"fast", "adaptive", "deep"}:
            return requested
        if len(items) <= policy.fast_candidate_limit and CognitiveReducer._item_chars(items) <= policy.fast_input_chars:
            return "fast"
        if len(items) >= policy.deep_candidate_threshold:
            return "deep"
        return "adaptive"

    @staticmethod
    def _bounded_items(items: List[Dict[str, Any]], max_chars: int) -> List[Dict[str, Any]]:
        bounded: List[Dict[str, Any]] = []
        used = 0
        for item in items:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            remaining = max_chars - used
            if remaining <= 0:
                break
            copied = dict(item)
            if len(content) > remaining:
                copied["content"] = content[:remaining]
            bounded.append(copied)
            used += len(str(copied.get("content") or ""))
        return bounded

    @staticmethod
    def _render_items(items: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for item in items:
            item_id = str(item.get("cognition_id") or item.get("memory_id") or "unknown")
            state = str(item.get("state") or "current")
            lines.append(f"[{item_id}] state={state} content={str(item.get('content') or '').strip()}")
        return "\n".join(lines)

    @staticmethod
    def _basis_memory_ids(items: List[Dict[str, Any]], source_ids: Iterable[Any]) -> List[str]:
        by_reference: Dict[str, str] = {}
        all_memory_ids: List[str] = []
        for item in items:
            memory_id = str(item.get("memory_id") or "").strip()
            if not memory_id:
                continue
            all_memory_ids.append(memory_id)
            by_reference[memory_id] = memory_id
            cognition_id = str(item.get("cognition_id") or "").strip()
            if cognition_id:
                by_reference[cognition_id] = memory_id
        resolved = list(dict.fromkeys(
            by_reference[str(reference)]
            for reference in source_ids
            if str(reference) in by_reference
        ))
        return resolved or list(dict.fromkeys(all_memory_ids))

    async def _json_call(self, *, system: str, payload: str) -> Optional[Dict[str, Any]]:
        if self.llm_call is None:
            return None
        response = await self.llm_call(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": payload},
            ]
        )
        if not isinstance(response, dict) or str(response.get("status") or "success") == "error":
            return None
        content = str(response.get("content") or "").strip()
        if content.startswith("```json") and content.endswith("```"):
            content = content[7:-3].strip()
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _decompose(
        self,
        *,
        query: str,
        facets: List[str],
        policy: CognitiveRecallPolicy,
    ) -> List[str]:
        supplied = [str(value).strip() for value in facets if str(value).strip()]
        if supplied:
            return supplied[: policy.max_channels]
        parsed = await self._json_call(
            system=(
                "Decompose the query only when independent cognitive evidence streams are needed. "
                "Return strict JSON: {\"channels\":[{\"question\":\"...\"}],\"coverage\":\"complete|partial\"}. "
                "Use one channel when decomposition would not improve retrieval."
            ),
            payload=query,
        )
        channels = parsed.get("channels") if isinstance(parsed, dict) else []
        out: List[str] = []
        for row in channels if isinstance(channels, list) else []:
            value = row.get("question") if isinstance(row, dict) else row
            text = str(value or "").strip()
            if text and text not in out:
                out.append(text)
        return (out or [query])[: policy.max_channels]

    async def _kernel(
        self,
        *,
        query: str,
        items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        parsed = await self._json_call(
            system=(
                "You are a cognition reduction kernel. Use only supplied records. "
                "Separate current facts, evolving state, uncertainty, and history. "
                "Return strict JSON with summary, relevant_ids, critical_ids, and uncertainties. "
                "Do not invent facts or persist anything."
            ),
            payload=f"Question:\n{query}\n\nRecords:\n{self._render_items(items)}",
        )
        if isinstance(parsed, dict) and str(parsed.get("summary") or "").strip():
            return {
                "question": query,
                "summary": str(parsed.get("summary") or "").strip(),
                "relevant_ids": [str(value) for value in parsed.get("relevant_ids") or []],
                "critical_ids": [str(value) for value in parsed.get("critical_ids") or []],
                "uncertainties": [str(value) for value in parsed.get("uncertainties") or []],
                "fallback": False,
            }
        return self._fallback_channel(query=query, items=items)

    @staticmethod
    def _fallback_channel(*, query: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        selected = items[:6]
        return {
            "question": query,
            "summary": "\n".join(f"- {str(item.get('content') or '').strip()}" for item in selected),
            "relevant_ids": [str(item.get("cognition_id") or item.get("memory_id") or "") for item in selected],
            "critical_ids": [],
            "uncertainties": [
                str(item.get("content") or "")
                for item in selected
                if str(item.get("state") or "") == "uncertain"
            ],
            "fallback": True,
        }

    @staticmethod
    def _partition(items: List[Dict[str, Any]], max_chars: int) -> List[List[Dict[str, Any]]]:
        """Build graph-aware receptive fields, then enforce the model budget."""
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        order: List[str] = []
        for item in items:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            related = item.get("related") if isinstance(item.get("related"), list) else []
            key = str(
                metadata.get("community_id")
                or metadata.get("cluster_id")
                or metadata.get("revision_chain_id")
                or (related[0] if related else "")
                or item.get("source_layer")
                or "unclustered"
            )
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(item)

        groups: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        current_chars = 0
        ordered_items = [item for key in order for item in buckets[key]]
        for item in ordered_items:
            size = len(str(item.get("content") or ""))
            if current and current_chars + size > max_chars:
                groups.append(current)
                current = []
                current_chars = 0
            current.append(item)
            current_chars += size
        if current:
            groups.append(current)
        return groups

    async def reduce(
        self,
        *,
        query: str,
        items: List[Dict[str, Any]],
        policy: CognitiveRecallPolicy,
        facets: Optional[List[str]] = None,
        requested_mode: str = "auto",
        deadline_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        bounded_items = list(items[: policy.candidate_pool_limit])
        skip_items, reducible = self._select_skip_buffer(bounded_items, policy)
        mode = self._resolve_mode(requested_mode, bounded_items, policy)
        metrics: Dict[str, Any] = {
            "mode": mode,
            "candidate_count": len(bounded_items),
            "skip_count": len(skip_items),
            "llm_calls": 0,
            "degraded": False,
        }

        if not policy.enabled or mode == "fast" or self.llm_call is None:
            channel = self._fallback_channel(query=query, items=bounded_items)
            metrics["degraded"] = mode != "fast" and self.llm_call is None
            metrics["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return {
                "version": "self_model.cognition_snapshot.v1",
                "mode": "fast" if not policy.enabled else mode,
                "query": query,
                "synthesis": channel["summary"],
                "channels": [channel],
                "critical_items": skip_items,
                "uncertainties": channel["uncertainties"],
                "source_ids": channel["relevant_ids"],
                "basis_memory_ids": self._basis_memory_ids(bounded_items, channel["relevant_ids"]),
                "metrics": metrics,
            }

        timeout_ms = min(policy.deadline_ms, max(250, int(deadline_ms or policy.deadline_ms)))
        semaphore = asyncio.Semaphore(policy.max_parallel_calls)
        call_count = 0

        async def guarded_kernel(channel_query: str, group: List[Dict[str, Any]]) -> Dict[str, Any]:
            nonlocal call_count
            if call_count >= policy.max_kernel_calls:
                return self._fallback_channel(query=channel_query, items=group)
            call_count += 1
            async with semaphore:
                return await self._kernel(query=channel_query, items=group)

        async def execute() -> List[Dict[str, Any]]:
            nonlocal call_count
            if not facets:
                call_count += 1
            channels = await self._decompose(
                query=query,
                facets=list(facets or []),
                policy=policy,
            )
            if mode == "adaptive":
                kernel_items = self._bounded_items(reducible or bounded_items, policy.kernel_input_chars)
                return await asyncio.gather(*(guarded_kernel(channel, kernel_items) for channel in channels))

            groups = self._partition(reducible or bounded_items, max(1000, policy.kernel_input_chars // 2))
            results: List[Dict[str, Any]] = []
            for channel in channels:
                local = await asyncio.gather(*(guarded_kernel(channel, group) for group in groups))
                if len(local) == 1 or policy.max_depth < 2:
                    results.append(local[0])
                    continue
                merged_items = [
                    {
                        "cognition_id": f"summary:{index + 1}",
                        "content": row.get("summary"),
                        "state": "current",
                    }
                    for index, row in enumerate(local)
                    if str(row.get("summary") or "").strip()
                ]
                results.append(await guarded_kernel(channel, merged_items))
            return results

        try:
            channels = await asyncio.wait_for(execute(), timeout=timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            channels = [self._fallback_channel(query=query, items=bounded_items)]
            metrics["degraded"] = True
            metrics["degraded_reason"] = "deadline_exceeded"

        metrics["llm_calls"] = call_count
        summaries = [str(channel.get("summary") or "").strip() for channel in channels if str(channel.get("summary") or "").strip()]
        source_ids = list(dict.fromkeys(
            str(value)
            for channel in channels
            for value in channel.get("relevant_ids") or []
            if str(value)
        ))
        uncertainties = list(dict.fromkeys(
            str(value)
            for channel in channels
            for value in channel.get("uncertainties") or []
            if str(value)
        ))
        metrics["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return {
            "version": "self_model.cognition_snapshot.v1",
            "mode": mode,
            "query": query,
            "synthesis": "\n\n".join(summaries),
            "channels": channels,
            "critical_items": skip_items,
            "uncertainties": uncertainties,
            "source_ids": source_ids,
            "basis_memory_ids": self._basis_memory_ids(bounded_items, source_ids),
            "metrics": metrics,
        }
