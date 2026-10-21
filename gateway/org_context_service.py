from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from .org_brain_store import OrgBrainStore


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
        store: Optional[OrgBrainStore] = None,
        event_emitter: Optional[Any] = None,
    ) -> None:
        self.config_service = config_service
        self.memory_service = memory_service
        self.llm_client = llm_client
        self.store = store or OrgBrainStore()
        self.event_emitter = event_emitter
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
            "chunk_chars": _as_int(raw.get("chunk_chars"), 5000, minimum=500, maximum=50000),
            "max_chunks": _as_int(raw.get("max_chunks"), 20, minimum=1, maximum=200),
            "personal_memory_collaboration": (
                _normalize_text(raw.get("personal_memory_collaboration") or "context_only").lower()
                if _normalize_text(raw.get("personal_memory_collaboration") or "context_only").lower()
                in {"off", "context_only"}
                else "context_only"
            ),
        }

    def is_enabled(self, user_config: Optional[Dict[str, Any]]) -> bool:
        profile = self.resolve_org_profile(user_config)
        return bool(profile["enabled"] and profile["org_id"])

    def _resolve_connector(self) -> Optional[Any]:
        adapter = getattr(self.memory_service, "memory_adapter", None) if self.memory_service else None
        hot = getattr(adapter, "hot_layer", None) if adapter else None
        connector = getattr(hot, "connector", None) if hot else None
        return connector

    def resolve_authorized_org(
        self,
        *,
        user_id: str,
        user_config: Optional[Dict[str, Any]],
        requested_org_id: Optional[str] = None,
        write: bool = False,
        admin: bool = False,
    ) -> tuple[str, Dict[str, Any]]:
        profile = self.resolve_org_profile(user_config)
        configured_org_id = _normalize_text(profile.get("org_id"))
        requested = _normalize_text(requested_org_id)
        if requested and configured_org_id and requested != configured_org_id:
            raise PermissionError("requested organization does not match the configured organization")
        org_id = requested or configured_org_id
        if not org_id:
            raise ValueError("org_id is required")
        self.store.ensure_organization(org_id=org_id, owner_user_id=user_id)
        membership = self.store.require_access(
            org_id=org_id,
            user_id=user_id,
            write=write,
            admin=admin,
        )
        return org_id, membership

    def component_status(self, *, user_id: str, user_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        profile = self.resolve_org_profile(user_config)
        enabled = bool(profile.get("enabled"))
        org_id = _normalize_text(profile.get("org_id"))
        connector = self._resolve_connector()
        result: Dict[str, Any] = {
            "installed": True,
            "enabled": enabled,
            "ready": False,
            "org_id": org_id,
            "backend": "neo4j" if connector else "sqlite",
            "graph_projection": bool(connector),
            "personal_memory_collaboration": profile.get("personal_memory_collaboration"),
        }
        if not enabled:
            result["reason"] = "disabled"
            return result
        if not org_id:
            result["reason"] = "org_id_required"
            return result
        try:
            self.resolve_authorized_org(user_id=user_id, user_config=user_config)
            result.update({"ready": True, "stats": self.store.stats(org_id=org_id, user_id=user_id)})
        except (PermissionError, ValueError) as exc:
            result["reason"] = str(exc)
        return result

    @staticmethod
    def _backend_notice(backend: str) -> Dict[str, Any]:
        backend_name = str(backend or "").strip().lower()
        out = {"core_capability": "graph_structure", "backend": backend_name or "unknown"}
        if "neo4j" not in backend_name:
            out["notice"] = (
                "Organization knowledge is persistent and available. Connect Neo4j to enable the optional graph projection."
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
        user_id: Optional[str] = None,
        source_title: Optional[str] = None,
        source_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        oid = _normalize_text(org_id)
        if not oid:
            return {"success": False, "message": "org_id is required", "accepted": 0}
        content = str(text or "").strip()
        if not content:
            return {"success": False, "message": "text is required", "accepted": 0}

        profile = self.resolve_org_profile(user_config)
        actor = _normalize_text(user_id or "local_owner")
        self.store.ensure_organization(org_id=oid, owner_user_id=actor)
        self.store.require_access(org_id=oid, user_id=actor, write=True)
        revision = self.store.create_revision(
            org_id=oid,
            user_id=actor,
            source_name=_normalize_text(source_doc_id),
            title=_normalize_text(source_title or source_doc_id),
            source_text=content,
            metadata=source_metadata,
            require_review=bool(profile.get("confirmation_queue")) if user_config is not None else False,
        )
        if revision.get("duplicate"):
            return {
                "success": True,
                "message": "document already ingested",
                "org_id": oid,
                "source_doc_id": source_doc_id,
                "accepted": 0,
                "duplicate": True,
                "revision": revision,
            }

        extract_limit = int(profile.get("extract_text_max_chars") or 5000)
        chunks = self._chunk_text(
            content,
            chunk_chars=min(int(profile.get("chunk_chars") or 5000), extract_limit),
            max_chunks=int(profile.get("max_chunks") or 20),
        )
        extracted: List[Dict[str, Any]] = []
        for chunk in chunks:
            extracted.extend(
                await self._extract_context_items(
                    text=chunk,
                    audience=audience,
                    register=register,
                    use_llm=use_llm,
                    extract_text_max_chars=extract_limit,
                    heuristic_max_lines=int(profile.get("heuristic_max_lines") or 30),
                    heuristic_max_items=int(profile.get("heuristic_max_items") or 15),
                    user_config=user_config,
                    user_id=actor,
                )
            )
        rows = [row for row in extracted if isinstance(row, dict)]
        if not rows:
            return {"success": True, "message": "no extractable org context", "accepted": 0}

        item_status = str(revision.get("status") or "pending")
        stored_rows = self.store.add_knowledge_items(
            org_id=oid,
            document_id=str(revision["document_id"]),
            revision_id=str(revision["revision_id"]),
            rows=rows,
            status=item_status,
        )

        accepted = 0
        connector = self._resolve_connector()
        if connector and item_status == "published":
            self._remove_document_projection(org_id=oid, document_id=str(revision["document_id"]))
            for row in stored_rows:
                ok = self._write_row_neo4j(
                    connector=connector,
                    org_id=oid,
                    source_doc_id=str(revision["document_id"]),
                    row=row,
                )
                if ok:
                    accepted += 1
        elif not connector and item_status == "published":
            async with self._lock:
                bucket = self._fallback_by_org.setdefault(oid, [])
                for row in stored_rows:
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
            "pending_review": len(stored_rows) if item_status == "pending" else 0,
            "total_candidates": len(rows),
            "revision": revision,
            "backend": "neo4j" if connector else "sqlite",
            **self._backend_notice("neo4j" if connector else "sqlite"),
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
        try:
            org_id, membership = self.resolve_authorized_org(
                user_id=user_id,
                user_config=user_config,
            )
        except (PermissionError, ValueError) as exc:
            return {"enabled": True, "recalled": False, "reason": "org_access_denied", "detail": str(exc)}
        aud = _normalize_text(audience or profile["audience_default"] or "")
        topic = _normalize_text(query)
        if not topic:
            return {"enabled": True, "recalled": False, "reason": "empty_topic", "org_id": profile["org_id"]}
        resolved_context_type = _normalize_text(context_type or profile.get("chat_context_type") or "chat")
        resolved_top_k = _as_int(top_k, int(profile.get("chat_top_k") or 5), minimum=1, maximum=50)
        return await self.recall_org_context(
            org_id=org_id,
            topic=topic,
            audience=aud,
            context_type=resolved_context_type,
            top_k=resolved_top_k,
            user_id=user_id,
            recall_priority=profile["recall_priority"],
            summary_label=str(profile.get("summary_label") or "Organization context hints"),
            summary_max_items=int(profile.get("summary_max_items") or 8),
            membership=membership,
            collaboration_mode=str(profile.get("personal_memory_collaboration") or "context_only"),
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
        membership: Optional[Dict[str, Any]] = None,
        collaboration_mode: str = "context_only",
    ) -> Dict[str, Any]:
        oid = _normalize_text(org_id)
        q = _normalize_text(topic)
        aud = _normalize_text(audience)
        actor = _normalize_text(user_id or "local_owner")
        if membership is None:
            self.store.ensure_organization(org_id=oid, owner_user_id=actor)
            membership = self.store.require_access(org_id=oid, user_id=actor)
        permission_revision = json.dumps(
            {"role": membership.get("role"), "audiences": membership.get("audiences") or []},
            ensure_ascii=False,
            sort_keys=True,
        )
        key = f"{oid}|{actor}|{permission_revision}|{q}|{aud}|{context_type}|{top_k}"
        now = time.time()
        cached = self._recall_cache.get(key)
        if cached and (now - float(cached.get("_ts", 0.0))) <= self._cache_ttl_s:
            return dict(cached.get("payload") or {})

        rows = await asyncio.to_thread(
            self.store.recall,
            org_id=oid,
            user_id=actor,
            topic=q,
            audience=aud,
            top_k=max(1, int(top_k)),
            context_type=context_type,
        )
        connector = self._resolve_connector()
        if rows:
            payload = {
                "recalled": True,
                "items": rows,
                "backend": "neo4j+sqlite" if connector else "sqlite",
                "recall_priority": recall_priority,
            }
        elif connector and not list(membership.get("audiences") or []):
            # Compatibility projection for organization graphs created before
            # the governed source store was introduced.
            payload = await asyncio.to_thread(
                self._recall_from_neo4j,
                connector=connector,
                org_id=oid,
                topic=q,
                audience=aud,
                top_k=max(1, int(top_k)),
                recall_priority=recall_priority,
            )
        else:
            payload = {"recalled": False, "items": [], "backend": "sqlite", "recall_priority": recall_priority}
        payload.setdefault("enabled", True)
        payload.setdefault("org_id", oid)
        payload.setdefault("topic", q)
        payload.setdefault("audience", aud)
        payload.setdefault("context_type", context_type)
        payload.setdefault("user_id", user_id)
        payload["membership"] = {
            "role": str(membership.get("role") or "reader"),
            "audiences": list(membership.get("audiences") or []),
        }
        payload["personal_memory_collaboration"] = collaboration_mode
        payload["isolation"] = "context_only_no_cross_write"
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

        actor = _normalize_text(user_id or "local_owner")
        self.store.ensure_organization(org_id=oid, owner_user_id=actor)
        membership = self.store.require_access(org_id=oid, user_id=actor)
        governed_rows = await asyncio.to_thread(
            self.store.recall,
            org_id=oid,
            user_id=actor,
            topic=q,
            audience=aud,
            top_k=lim,
            context_type="graph",
        )

        connector = self._resolve_connector()
        restricted_audiences = list(membership.get("audiences") or [])
        if connector and not governed_rows and not restricted_audiences:
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

        rows = governed_rows
        if not rows:
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
            "backend": "neo4j+sqlite" if connector else "sqlite",
            "nodes": list(nodes.values()),
            "edges": edges,
            "stats": {"nodes": len(nodes), "edges": len(edges)},
            **self._backend_notice("neo4j" if connector else "sqlite"),
        }

    def list_documents(self, *, org_id: str, user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.store.list_documents(org_id=org_id, user_id=user_id, status=status)

    def list_members(self, *, org_id: str, user_id: str) -> List[Dict[str, Any]]:
        return self.store.list_members(org_id=org_id, user_id=user_id)

    def upsert_member(self, *, org_id: str, actor_user_id: str, user_id: str, role: str, audiences: Optional[List[str]] = None) -> Dict[str, Any]:
        self._recall_cache.clear()
        return self.store.upsert_member(
            org_id=org_id,
            actor_user_id=actor_user_id,
            user_id=user_id,
            role=role,
            audiences=audiences,
        )

    def export_bundle(self, *, org_id: str, user_id: str) -> Dict[str, Any]:
        return self.store.export_bundle(org_id=org_id, user_id=user_id)

    def list_audit_events(self, *, org_id: str, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.store.list_audit_events(org_id=org_id, user_id=user_id, limit=limit)

    def revoke_document(self, *, org_id: str, user_id: str, document_id: str) -> Dict[str, Any]:
        result = self.store.revoke_document(org_id=org_id, user_id=user_id, document_id=document_id)
        self._remove_document_projection(org_id=org_id, document_id=document_id)
        self._recall_cache.clear()
        return result

    def import_bundle(self, *, bundle: Dict[str, Any], user_id: str, target_org_id: Optional[str] = None) -> Dict[str, Any]:
        result = self.store.import_bundle(bundle=bundle, user_id=user_id, target_org_id=target_org_id)
        org_id = str(result.get("org_id") or "")
        connector = self._resolve_connector()
        if connector and org_id:
            projected = 0
            for row in self.store.published_items(org_id=org_id, user_id=user_id):
                if self._write_row_neo4j(
                    connector=connector,
                    org_id=org_id,
                    source_doc_id=str(row.get("document_id") or ""),
                    row=row,
                ):
                    projected += 1
            result["projected_items"] = projected
        self._recall_cache.clear()
        return result

    async def review_revision(self, *, org_id: str, user_id: str, revision_id: str, approve: bool) -> Dict[str, Any]:
        result = self.store.review_revision(
            org_id=org_id,
            user_id=user_id,
            revision_id=revision_id,
            approve=approve,
        )
        if approve:
            connector = self._resolve_connector()
            if connector:
                self._remove_document_projection(org_id=org_id, document_id=str(result.get("document_id") or ""))
                rows = self.store.revision_items(org_id=org_id, user_id=user_id, revision_id=revision_id)
                projected = 0
                for row in rows:
                    if self._write_row_neo4j(
                        connector=connector,
                        org_id=org_id,
                        source_doc_id=str(row.get("document_id") or ""),
                        row=row,
                    ):
                        projected += 1
                result["projected_items"] = projected
        self._recall_cache.clear()
        return result

    def _remove_document_projection(self, *, org_id: str, document_id: str) -> None:
        connector = self._resolve_connector()
        if connector is None or not document_id:
            return
        try:
            connector.query(
                """
                MATCH (e:OrgExpression {org_id: $org_id, source_doc_id: $document_id})
                DETACH DELETE e
                """,
                {"org_id": org_id, "document_id": document_id},
            )
        except Exception as exc:
            logger.debug("OrgContextService: remove document projection failed: {}", exc)

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
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        aud = _normalize_text(audience or "")
        reg = _normalize_text(register or "")
        if use_llm and self.llm_client and hasattr(self.llm_client, "call_llm"):
            prompt_system = (
                "Extract enterprise expression context from document text.\n"
                "Output strict JSON: {\"items\":[{\"concept\":\"...\",\"expression\":\"...\",\"knowledge_kind\":"
                "\"fact|policy|style|terminology|template\",\"audience\":\"...\",\"register\":\"...\","
                "\"terms_locked\":[...],\"confidence\":0.0-1.0}]}"
            )
            prompt_user = (
                f"Document:\n{text[: max(1, int(extract_text_max_chars))]}\n\n"
                f"Default audience: {aud or 'unknown'}\nDefault register: {reg or 'unknown'}\n"
            )
            try:
                out = await self.llm_client.call_llm(
                    [{"role": "system", "content": prompt_system}, {"role": "user", "content": prompt_user}],
                    user_config=user_config,
                    user_id=user_id,
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
                            "knowledge_kind": _normalize_text(row.get("knowledge_kind") or "fact").lower(),
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
    def _chunk_text(text: str, *, chunk_chars: int, max_chunks: int) -> List[str]:
        content = str(text or "").strip()
        if not content:
            return []
        size = max(500, int(chunk_chars))
        limit = max(1, int(max_chunks))
        chunks: List[str] = []
        cursor = 0
        while cursor < len(content) and len(chunks) < limit:
            end = min(len(content), cursor + size)
            if end < len(content):
                boundary = content.rfind("\n", cursor + size // 2, end)
                if boundary > cursor:
                    end = boundary
            chunk = content[cursor:end].strip()
            if chunk:
                chunks.append(chunk)
            cursor = max(end, cursor + 1)
        return chunks

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
            concept = ln[:32].strip()
            if not concept:
                continue
            picked.append(
                {
                    "concept": concept,
                    "expression": ln[:200],
                    "knowledge_kind": "fact",
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
        revision_id = _normalize_text(row.get("revision_id"))
        knowledge_kind = _normalize_text(row.get("knowledge_kind") or "fact")

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
            "revision_id": revision_id,
            "knowledge_kind": knowledge_kind,
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
            e.revision_id = $revision_id,
            e.knowledge_kind = $knowledge_kind,
            e.lifecycle_status = 'published',
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
        WHERE (toLower(c.name) CONTAINS toLower($topic)
           OR toLower(e.text) CONTAINS toLower($topic))
          AND coalesce(e.lifecycle_status, 'published') = 'published'
        WITH c, e, r,
             CASE WHEN $audience <> '' AND e.audience = $audience THEN 1 ELSE 0 END AS audience_hit
        RETURN c.name as concept,
               e.text as expression,
               e.audience as audience,
               e.register as register,
               e.knowledge_kind as knowledge_kind,
               e.source_doc_id as source_doc_id,
               e.revision_id as revision_id,
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
            knowledge_kind = _normalize_text(row.get("knowledge_kind") or "fact")
            source = _normalize_text(row.get("source_name") or row.get("source_doc_id") or row.get("document_id"))
            if not concept or not expression:
                continue
            tag = f"[{knowledge_kind}/{audience or 'general'}/{register or 'default'}]"
            citation = f" (source: {source})" if source else ""
            lines.append(f"{tag} {concept}: {expression}{citation}")
        if not lines:
            return ""
        return (
            f"{label} (governed organization evidence; keep separate from personal memory and do not write across scopes):\n- "
            + "\n- ".join(lines)
        )

