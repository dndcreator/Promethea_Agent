from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger


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


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_json(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _hash_id(prefix: str, payload: str) -> str:
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_int(value: Any, default: int, *, minimum: int = 0, maximum: Optional[int] = None) -> int:
    try:
        out = int(value)
    except Exception:
        out = int(default)
    out = max(minimum, out)
    if maximum is not None:
        out = min(maximum, out)
    return out


def _as_suffix_list(value: Any, default: List[str]) -> List[str]:
    if value is None:
        items = list(default)
    elif isinstance(value, list):
        items = [str(x or "").strip().lower() for x in value]
    elif isinstance(value, str):
        raw = value.strip()
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                items = [str(x or "").strip().lower() for x in parsed] if isinstance(parsed, list) else list(default)
            except Exception:
                items = [part.strip().lower() for part in raw.split(",") if part.strip()]
        else:
            items = [part.strip().lower() for part in raw.split(",") if part.strip()]
    else:
        items = list(default)
    normalized: List[str] = []
    for item in items:
        if not item:
            continue
        if not item.startswith("."):
            item = "." + item
        normalized.append(item)
    if not normalized:
        normalized = list(default)
    return sorted(list(dict.fromkeys(normalized)))


class OrgContextService:
    """
    B-side organization context service.

    Goals:
    - Keep enterprise context isolated by org_id (while preserving user_id isolation).
    - Provide ingest + recall APIs that are pluggable and fail-soft.
    - Avoid coupling with personal mode when org_brain.enabled is false.
    """

    def __init__(
        self,
        *,
        config_service: Optional[Any] = None,
        memory_service: Optional[Any] = None,
        llm_client: Optional[Any] = None,
    ) -> None:
        self.config_service = config_service
        self.memory_service = memory_service
        self.llm_client = llm_client
        self._fallback_by_org: Dict[str, List[Dict[str, Any]]] = {}
        self._recall_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl_s = 15.0
        self._lock = asyncio.Lock()

    @staticmethod
    def resolve_org_profile(user_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = user_config if isinstance(user_config, dict) else {}
        raw = cfg.get("org_brain") if isinstance(cfg.get("org_brain"), dict) else {}
        recall_priority = _normalize_text(raw.get("recall_priority") or "blend").lower()
        if recall_priority not in {"blend", "override_persona"}:
            recall_priority = "blend"
        allowed_suffixes = _as_suffix_list(
            raw.get("allowed_suffixes"),
            [".txt", ".md", ".markdown", ".csv", ".json", ".docx", ".pdf"],
        )
        return {
            "enabled": _to_bool(raw.get("enabled"), default=False),
            "org_id": _normalize_text(raw.get("org_id")),
            "recall_priority": recall_priority,
            "confirmation_queue": _to_bool(raw.get("confirmation_queue"), default=True),
            "audience_default": _normalize_text(raw.get("audience_default") or "business"),
            "max_upload_bytes": _as_int(raw.get("max_upload_bytes"), 10 * 1024 * 1024, minimum=1024, maximum=100 * 1024 * 1024),
            "allowed_suffixes": allowed_suffixes,
            "recall_top_k_default": _as_int(raw.get("recall_top_k_default"), 5, minimum=1, maximum=50),
            "recall_context_type_default": _normalize_text(raw.get("recall_context_type_default") or "writing"),
            "chat_top_k": _as_int(raw.get("chat_top_k"), 5, minimum=1, maximum=50),
            "chat_context_type": _normalize_text(raw.get("chat_context_type") or "chat"),
            "summary_label": _normalize_text(raw.get("summary_label") or "Organization context hints"),
            "summary_max_items": _as_int(raw.get("summary_max_items"), 8, minimum=1, maximum=50),
            "extract_text_max_chars": _as_int(raw.get("extract_text_max_chars"), 5000, minimum=500, maximum=200000),
            "heuristic_max_lines": _as_int(raw.get("heuristic_max_lines"), 30, minimum=1, maximum=1000),
            "heuristic_max_items": _as_int(raw.get("heuristic_max_items"), 15, minimum=1, maximum=200),
        }

    def is_enabled(self, user_config: Optional[Dict[str, Any]]) -> bool:
        profile = self.resolve_org_profile(user_config)
        return bool(profile["enabled"] and profile["org_id"])

    def _resolve_connector(self) -> Optional[Any]:
        adapter = getattr(self.memory_service, "memory_adapter", None) if self.memory_service else None
        hot = getattr(adapter, "hot_layer", None) if adapter else None
        connector = getattr(hot, "connector", None) if hot else None
        return connector

    @staticmethod
    def _backend_notice(backend: str) -> Dict[str, Any]:
        backend_name = str(backend or "").strip().lower()
        out = {"core_capability": "graph_structure", "backend": backend_name or "unknown"}
        if backend_name != "neo4j":
            out["notice"] = (
                "Org brain is running in fallback mode. Core enterprise capability is graph-structured knowledge; "
                "connect Neo4j for full graph recall and visualization fidelity."
            )
        return out

    async def ingest_document(
        self,
        *,
        org_id: str,
        text: str,
        source_doc_id: str,
        audience: Optional[str] = None,
        register: Optional[str] = None,
        use_llm: bool = True,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        oid = _normalize_text(org_id)
        if not oid:
            return {"success": False, "message": "org_id is required", "accepted": 0}
        content = str(text or "").strip()
        if not content:
            return {"success": False, "message": "text is required", "accepted": 0}

        profile = self.resolve_org_profile(user_config)
        extracted = await self._extract_context_items(
            text=content,
            audience=audience,
            register=register,
            use_llm=use_llm,
            extract_text_max_chars=int(profile.get("extract_text_max_chars") or 5000),
            heuristic_max_lines=int(profile.get("heuristic_max_lines") or 30),
            heuristic_max_items=int(profile.get("heuristic_max_items") or 15),
        )
        rows = [row for row in extracted if isinstance(row, dict)]
        if not rows:
            return {"success": True, "message": "no extractable org context", "accepted": 0}

        accepted = 0
        connector = self._resolve_connector()
        if connector:
            for row in rows:
                ok = self._write_row_neo4j(
                    connector=connector,
                    org_id=oid,
                    source_doc_id=source_doc_id,
                    row=row,
                )
                if ok:
                    accepted += 1
        else:
            async with self._lock:
                bucket = self._fallback_by_org.setdefault(oid, [])
                for row in rows:
                    bucket.append(
                        {
                            "org_id": oid,
                            "source_doc_id": source_doc_id,
                            "concept": _normalize_text(row.get("concept")),
                            "expression": _normalize_text(row.get("expression")),
                            "audience": _normalize_text(row.get("audience") or audience or ""),
                            "register": _normalize_text(row.get("register") or register or ""),
                            "terms_locked": [str(x).strip() for x in (row.get("terms_locked") or []) if str(x).strip()],
                            "confidence": _as_float(row.get("confidence", 0.5), 0.5),
                            "updated_at": _utc_iso(),
                        }
                    )
                    accepted += 1

        return {
            "success": True,
            "message": "ingested",
            "org_id": oid,
            "source_doc_id": source_doc_id,
            "accepted": accepted,
            "total_candidates": len(rows),
            "backend": "neo4j" if connector else "in_memory_fallback",
            **self._backend_notice("neo4j" if connector else "in_memory_fallback"),
        }

    async def recall_for_turn(
        self,
        *,
        query: str,
        user_id: str,
        user_config: Optional[Dict[str, Any]],
        audience: Optional[str] = None,
        context_type: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        profile = self.resolve_org_profile(user_config)
        if not (profile["enabled"] and profile["org_id"]):
            return {"enabled": False, "recalled": False, "reason": "org_brain_disabled"}
        aud = _normalize_text(audience or profile["audience_default"] or "")
        topic = _normalize_text(query)
        if not topic:
            return {"enabled": True, "recalled": False, "reason": "empty_topic", "org_id": profile["org_id"]}
        resolved_context_type = _normalize_text(context_type or profile.get("chat_context_type") or "chat")
        resolved_top_k = _as_int(top_k, int(profile.get("chat_top_k") or 5), minimum=1, maximum=50)
        return await self.recall_org_context(
            org_id=profile["org_id"],
            topic=topic,
            audience=aud,
            context_type=resolved_context_type,
            top_k=resolved_top_k,
            user_id=user_id,
            recall_priority=profile["recall_priority"],
            summary_label=str(profile.get("summary_label") or "Organization context hints"),
            summary_max_items=int(profile.get("summary_max_items") or 8),
        )

    async def recall_org_context(
        self,
        *,
        org_id: str,
        topic: str,
        audience: str,
        context_type: str,
        top_k: int,
        user_id: Optional[str] = None,
        recall_priority: str = "blend",
        summary_label: str = "Organization context hints",
        summary_max_items: int = 8,
    ) -> Dict[str, Any]:
        oid = _normalize_text(org_id)
        q = _normalize_text(topic)
        aud = _normalize_text(audience)
        key = f"{oid}|{q}|{aud}|{context_type}|{top_k}"
        now = time.time()
        cached = self._recall_cache.get(key)
        if cached and (now - float(cached.get("_ts", 0.0))) <= self._cache_ttl_s:
            return dict(cached.get("payload") or {})

        connector = self._resolve_connector()
        if connector:
            payload = self._recall_from_neo4j(
                connector=connector,
                org_id=oid,
                topic=q,
                audience=aud,
                top_k=max(1, int(top_k)),
                recall_priority=recall_priority,
            )
        else:
            payload = await self._recall_from_fallback(
                org_id=oid,
                topic=q,
                audience=aud,
                top_k=max(1, int(top_k)),
                recall_priority=recall_priority,
            )
        payload.setdefault("enabled", True)
        payload.setdefault("org_id", oid)
        payload.setdefault("topic", q)
        payload.setdefault("audience", aud)
        payload.setdefault("context_type", context_type)
        payload.setdefault("user_id", user_id)
        payload["summary_text"] = self._render_summary(
            payload,
            label=_normalize_text(summary_label or "Organization context hints"),
            max_items=_as_int(summary_max_items, 8, minimum=1, maximum=50),
        )
        payload.update(self._backend_notice(str(payload.get("backend") or "")))

        self._recall_cache[key] = {"_ts": now, "payload": payload}
        return payload

    async def get_visual_graph(
        self,
        *,
        org_id: str,
        topic: str = "",
        audience: str = "",
        limit_nodes: int = 200,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        oid = _normalize_text(org_id)
        q = _normalize_text(topic).lower()
        aud = _normalize_text(audience)
        lim = _as_int(limit_nodes, 200, minimum=1, maximum=500)

        connector = self._resolve_connector()
        if connector:
            rows = connector.query(
                """
                MATCH (c:OrgConcept {org_id: $org_id})-[r:EXPRESSED_AS]->(e:OrgExpression {org_id: $org_id})
                WHERE ($topic = ''
                    OR toLower(c.name) CONTAINS $topic
                    OR toLower(e.text) CONTAINS $topic)
                  AND ($audience = '' OR e.audience = $audience)
                RETURN c.id as concept_id,
                       c.name as concept,
                       e.id as expression_id,
                       e.text as expression,
                       e.audience as audience,
                       e.register as register,
                       coalesce(e.source_doc_id, c.last_source_doc_id, '') as source_doc_id,
                       coalesce(e.confidence, r.confidence, 0.5) as confidence
                ORDER BY confidence DESC
                LIMIT $limit
                """,
                {
                    "org_id": oid,
                    "topic": q,
                    "audience": aud,
                    "limit": lim,
                },
            )
            nodes: Dict[str, Dict[str, Any]] = {}
            edges: List[Dict[str, Any]] = []
            for row in rows or []:
                concept_id = str(row.get("concept_id") or "")
                expression_id = str(row.get("expression_id") or "")
                if not concept_id or not expression_id:
                    continue
                concept_node_id = f"concept:{concept_id}"
                expr_node_id = f"expression:{expression_id}"
                if concept_node_id not in nodes:
                    nodes[concept_node_id] = {
                        "id": concept_node_id,
                        "type": "concept",
                        "label": str(row.get("concept") or concept_id),
                        "org_id": oid,
                    }
                if expr_node_id not in nodes:
                    nodes[expr_node_id] = {
                        "id": expr_node_id,
                        "type": "expression",
                        "label": str(row.get("expression") or ""),
                        "org_id": oid,
                        "audience": str(row.get("audience") or ""),
                        "register": str(row.get("register") or ""),
                        "source_doc_id": str(row.get("source_doc_id") or ""),
                    }
                edges.append(
                    {
                        "id": f"edge:{concept_id}:{expression_id}",
                        "type": "EXPRESSED_AS",
                        "source": concept_node_id,
                        "target": expr_node_id,
                        "weight": _as_float(row.get("confidence", 0.5), 0.5),
                    }
                )
            return {
                "enabled": True,
                "org_id": oid,
                "topic": q,
                "audience": aud,
                "user_id": user_id,
                "backend": "neo4j",
                "nodes": list(nodes.values()),
                "edges": edges,
                "stats": {"nodes": len(nodes), "edges": len(edges)},
                **self._backend_notice("neo4j"),
            }

        async with self._lock:
            rows = list(self._fallback_by_org.get(oid) or [])
        if q:
            rows = [
                row
                for row in rows
                if q in str(row.get("concept") or "").lower() or q in str(row.get("expression") or "").lower()
            ]
        if aud:
            rows = [row for row in rows if str(row.get("audience") or "") == aud]
        rows.sort(key=lambda row: -_as_float(row.get("confidence", 0.5), 0.5))
        rows = rows[:lim]

        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows):
            concept = _normalize_text(row.get("concept"))
            expression = _normalize_text(row.get("expression"))
            if not concept or not expression:
                continue
            concept_id = _hash_id("concept", f"{oid}|{concept}")
            expression_id = _hash_id("expression", f"{oid}|{concept}|{expression}|{idx}")
            concept_node_id = f"concept:{concept_id}"
            expr_node_id = f"expression:{expression_id}"
            if concept_node_id not in nodes:
                nodes[concept_node_id] = {
                    "id": concept_node_id,
                    "type": "concept",
                    "label": concept,
                    "org_id": oid,
                }
            if expr_node_id not in nodes:
                nodes[expr_node_id] = {
                    "id": expr_node_id,
                    "type": "expression",
                    "label": expression,
                    "org_id": oid,
                    "audience": str(row.get("audience") or ""),
                    "register": str(row.get("register") or ""),
                    "source_doc_id": str(row.get("source_doc_id") or ""),
                }
            edges.append(
                {
                    "id": f"edge:{concept_id}:{expression_id}",
                    "type": "EXPRESSED_AS",
                    "source": concept_node_id,
                    "target": expr_node_id,
                    "weight": _as_float(row.get("confidence", 0.5), 0.5),
                }
            )
        return {
            "enabled": True,
            "org_id": oid,
            "topic": q,
            "audience": aud,
            "user_id": user_id,
            "backend": "in_memory_fallback",
            "nodes": list(nodes.values()),
            "edges": edges,
            "stats": {"nodes": len(nodes), "edges": len(edges)},
            **self._backend_notice("in_memory_fallback"),
        }

    async def _extract_context_items(
        self,
        *,
        text: str,
        audience: Optional[str],
        register: Optional[str],
        use_llm: bool,
        extract_text_max_chars: int,
        heuristic_max_lines: int,
        heuristic_max_items: int,
    ) -> List[Dict[str, Any]]:
        aud = _normalize_text(audience or "")
        reg = _normalize_text(register or "")
        if use_llm and self.llm_client and hasattr(self.llm_client, "call_llm"):
            prompt_system = (
                "Extract enterprise expression context from document text.\n"
                "Output strict JSON: {\"items\":[{\"concept\":\"...\",\"expression\":\"...\",\"audience\":\"...\","
                "\"register\":\"...\",\"terms_locked\":[...],\"confidence\":0.0-1.0}]}"
            )
            prompt_user = (
                f"Document:\n{text[: max(1, int(extract_text_max_chars))]}\n\n"
                f"Default audience: {aud or 'unknown'}\nDefault register: {reg or 'unknown'}\n"
            )
            try:
                out = await self.llm_client.call_llm(
                    [{"role": "system", "content": prompt_system}, {"role": "user", "content": prompt_user}],
                    user_config=None,
                    user_id=None,
                )
                data = _extract_json(str((out or {}).get("content") or ""))
                rows = data.get("items") if isinstance(data.get("items"), list) else []
                cleaned: List[Dict[str, Any]] = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    concept = _normalize_text(row.get("concept"))
                    expr = _normalize_text(row.get("expression"))
                    if not concept or not expr:
                        continue
                    cleaned.append(
                        {
                            "concept": concept,
                            "expression": expr,
                            "audience": _normalize_text(row.get("audience") or aud),
                            "register": _normalize_text(row.get("register") or reg),
                            "terms_locked": [
                                str(x).strip()
                                for x in (row.get("terms_locked") or [])
                                if str(x).strip()
                            ],
                            "confidence": _as_float(row.get("confidence", 0.6), 0.6),
                        }
                    )
                if cleaned:
                    return cleaned
            except Exception as e:
                logger.debug("OrgContextService: llm extract failed, fallback to heuristic: {}", e)

        return self._heuristic_extract(
            text=text,
            audience=aud,
            register=reg,
            max_lines=_as_int(heuristic_max_lines, 30, minimum=1, maximum=1000),
            max_items=_as_int(heuristic_max_items, 15, minimum=1, maximum=200),
        )

    @staticmethod
    def _heuristic_extract(
        *,
        text: str,
        audience: str,
        register: str,
        max_lines: int = 30,
        max_items: int = 15,
    ) -> List[Dict[str, Any]]:
        lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
        picked = []
        for ln in lines[: max(1, int(max_lines))]:
            if len(ln) < 6:
                continue
            concept = ln.split("：", 1)[0].split(":", 1)[0].strip()
            if not concept or len(concept) > 32:
                continue
            picked.append(
                {
                    "concept": concept,
                    "expression": ln[:200],
                    "audience": audience,
                    "register": register,
                    "terms_locked": [],
                    "confidence": 0.45,
                }
            )
        return picked[: max(1, int(max_items))]

    def _write_row_neo4j(
        self,
        *,
        connector: Any,
        org_id: str,
        source_doc_id: str,
        row: Dict[str, Any],
    ) -> bool:
        concept = _normalize_text(row.get("concept"))
        expression = _normalize_text(row.get("expression"))
        if not concept or not expression:
            return False
        audience = _normalize_text(row.get("audience"))
        register = _normalize_text(row.get("register"))
        confidence = _as_float(row.get("confidence", 0.5), 0.5)
        terms_locked = [str(x).strip() for x in (row.get("terms_locked") or []) if str(x).strip()]

        concept_id = _hash_id("org_concept", f"{org_id}|{concept}")
        expr_id = _hash_id("org_expr", f"{org_id}|{concept}|{audience}|{register}|{expression}")
        params = {
            "org_id": org_id,
            "source_doc_id": source_doc_id,
            "concept_id": concept_id,
            "expr_id": expr_id,
            "concept": concept,
            "expression": expression,
            "audience": audience,
            "register": register,
            "confidence": confidence,
            "terms_locked": terms_locked,
            "updated_at": _utc_iso(),
        }
        cypher = """
        MERGE (c:OrgConcept {id: $concept_id})
        SET c.org_id = $org_id,
            c.name = $concept,
            c.updated_at = datetime($updated_at),
            c.last_source_doc_id = $source_doc_id
        MERGE (e:OrgExpression {id: $expr_id})
        SET e.org_id = $org_id,
            e.text = $expression,
            e.audience = $audience,
            e.register = $register,
            e.confidence = $confidence,
            e.terms_locked = $terms_locked,
            e.source_doc_id = $source_doc_id,
            e.updated_at = datetime($updated_at)
        MERGE (c)-[r:EXPRESSED_AS {audience: $audience, register: $register}]->(e)
        SET r.confidence = $confidence,
            r.updated_at = datetime($updated_at)
        """
        try:
            connector.query(cypher, params)
            return True
        except Exception as e:
            logger.debug("OrgContextService: write neo4j failed: {}", e)
            return False

    def _recall_from_neo4j(
        self,
        *,
        connector: Any,
        org_id: str,
        topic: str,
        audience: str,
        top_k: int,
        recall_priority: str,
    ) -> Dict[str, Any]:
        q = """
        MATCH (c:OrgConcept {org_id: $org_id})-[r:EXPRESSED_AS]->(e:OrgExpression {org_id: $org_id})
        WHERE toLower(c.name) CONTAINS toLower($topic)
           OR toLower(e.text) CONTAINS toLower($topic)
        WITH c, e, r,
             CASE WHEN $audience <> '' AND e.audience = $audience THEN 1 ELSE 0 END AS audience_hit
        RETURN c.name as concept,
               e.text as expression,
               e.audience as audience,
               e.register as register,
               coalesce(e.terms_locked, []) as terms_locked,
               coalesce(e.confidence, r.confidence, 0.5) as confidence,
               audience_hit as audience_hit
        ORDER BY audience_hit DESC, confidence DESC
        LIMIT $top_k
        """
        rows = connector.query(
            q,
            {
                "org_id": org_id,
                "topic": topic,
                "audience": audience,
                "top_k": max(1, int(top_k)),
            },
        )
        items = [dict(row) for row in (rows or [])]
        return {
            "recalled": bool(items),
            "backend": "neo4j",
            "recall_priority": recall_priority,
            "items": items,
        }

    async def _recall_from_fallback(
        self,
        *,
        org_id: str,
        topic: str,
        audience: str,
        top_k: int,
        recall_priority: str,
    ) -> Dict[str, Any]:
        async with self._lock:
            rows = list(self._fallback_by_org.get(org_id) or [])
        if not rows:
            return {
                "recalled": False,
                "backend": "in_memory_fallback",
                "recall_priority": recall_priority,
                "items": [],
            }
        needle = topic.lower()
        out: List[Dict[str, Any]] = []
        for row in rows:
            concept = str(row.get("concept") or "")
            expr = str(row.get("expression") or "")
            if needle not in concept.lower() and needle not in expr.lower():
                continue
            rank = _as_float(row.get("confidence", 0.5), 0.5)
            if audience and str(row.get("audience") or "") == audience:
                rank += 1.0
            item = dict(row)
            item["_rank"] = rank
            out.append(item)
        out.sort(key=lambda x: (-float(x.get("_rank", 0.0)), str(x.get("concept") or "")))
        items = [{k: v for k, v in row.items() if k != "_rank"} for row in out[: max(1, int(top_k))]]
        return {
            "recalled": bool(items),
            "backend": "in_memory_fallback",
            "recall_priority": recall_priority,
            "items": items,
        }

    @staticmethod
    def _render_summary(payload: Dict[str, Any], *, label: str = "Organization context hints", max_items: int = 8) -> str:
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        if not items:
            return ""
        lines: List[str] = []
        for row in items[: max(1, int(max_items))]:
            if not isinstance(row, dict):
                continue
            concept = _normalize_text(row.get("concept"))
            expression = _normalize_text(row.get("expression"))
            audience = _normalize_text(row.get("audience"))
            register = _normalize_text(row.get("register"))
            if not concept or not expression:
                continue
            tag = f"[{audience or 'general'}/{register or 'default'}]"
            lines.append(f"{tag} {concept}: {expression}")
        if not lines:
            return ""
        return f"{label}:\n- " + "\n- ".join(lines)

