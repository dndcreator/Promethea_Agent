from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = 1
MEMBER_ROLES = {"owner", "admin", "editor", "reader"}
WRITE_ROLES = {"owner", "admin", "editor"}
ADMIN_ROLES = {"owner", "admin"}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class OrgBrainStore:
    """Persistent governance and source-of-truth storage for an organization brain.

    Neo4j and other retrieval backends are projections. Organization membership,
    source lineage, review state, and portable knowledge remain backend-neutral.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._memory_connection: Optional[sqlite3.Connection] = None
        if self.path is None:
            self._memory_connection = sqlite3.connect(":memory:", check_same_thread=False)
            self._configure(self._memory_connection)
        self._initialize()

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

    def _connect(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            return self._memory_connection
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self._configure(connection)
        return connection

    def _close(self, connection: sqlite3.Connection) -> None:
        if connection is not self._memory_connection:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            with self._lock, connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS organizations (
                        org_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    );

                    CREATE TABLE IF NOT EXISTS org_members (
                        org_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        audiences_json TEXT NOT NULL DEFAULT '[]',
                        status TEXT NOT NULL DEFAULT 'active',
                        joined_at TEXT NOT NULL,
                        PRIMARY KEY (org_id, user_id),
                        FOREIGN KEY (org_id) REFERENCES organizations(org_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS org_documents (
                        document_id TEXT PRIMARY KEY,
                        org_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        source_name TEXT NOT NULL,
                        current_revision INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'active',
                        created_by TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        UNIQUE (org_id, source_name),
                        FOREIGN KEY (org_id) REFERENCES organizations(org_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS org_document_revisions (
                        revision_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL,
                        revision_number INTEGER NOT NULL,
                        content_sha256 TEXT NOT NULL,
                        source_text TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        reviewed_by TEXT,
                        reviewed_at TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        UNIQUE (document_id, revision_number),
                        UNIQUE (document_id, content_sha256),
                        FOREIGN KEY (document_id) REFERENCES org_documents(document_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS org_knowledge_items (
                        item_id TEXT PRIMARY KEY,
                        org_id TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        revision_id TEXT NOT NULL,
                        concept TEXT NOT NULL,
                        expression TEXT NOT NULL,
                        knowledge_kind TEXT NOT NULL DEFAULT 'fact',
                        audience TEXT NOT NULL DEFAULT '',
                        register_name TEXT NOT NULL DEFAULT '',
                        terms_json TEXT NOT NULL DEFAULT '[]',
                        confidence REAL NOT NULL DEFAULT 0.5,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (org_id) REFERENCES organizations(org_id) ON DELETE CASCADE,
                        FOREIGN KEY (document_id) REFERENCES org_documents(document_id) ON DELETE CASCADE,
                        FOREIGN KEY (revision_id) REFERENCES org_document_revisions(revision_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS org_audit_events (
                        event_id TEXT PRIMARY KEY,
                        org_id TEXT NOT NULL,
                        actor_user_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        subject_type TEXT NOT NULL,
                        subject_id TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        details_json TEXT NOT NULL DEFAULT '{}'
                    );

                    CREATE INDEX IF NOT EXISTS idx_org_members_user ON org_members(user_id, status);
                    CREATE INDEX IF NOT EXISTS idx_org_documents_org ON org_documents(org_id, updated_at);
                    CREATE INDEX IF NOT EXISTS idx_org_revisions_document ON org_document_revisions(document_id, revision_number);
                    CREATE INDEX IF NOT EXISTS idx_org_items_recall ON org_knowledge_items(org_id, status, audience);
                    CREATE INDEX IF NOT EXISTS idx_org_audit_org ON org_audit_events(org_id, occurred_at);
                    """
                )
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        finally:
            self._close(connection)

    @staticmethod
    def _row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        out = dict(row)
        for key in ("metadata_json", "audiences_json", "terms_json", "details_json"):
            if key in out:
                target = key.removesuffix("_json")
                try:
                    out[target] = json.loads(str(out.pop(key) or ("[]" if key != "metadata_json" and key != "details_json" else "{}")))
                except Exception:
                    out[target] = [] if key in {"audiences_json", "terms_json"} else {}
        if "register_name" in out:
            out["register"] = out.pop("register_name")
        if "terms" in out:
            out["terms_locked"] = list(out["terms"] or [])
        return out

    def _audit(self, connection: sqlite3.Connection, *, org_id: str, actor: str, action: str, subject_type: str, subject_id: str, details: Optional[Dict[str, Any]] = None) -> None:
        connection.execute(
            "INSERT INTO org_audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, org_id, actor, action, subject_type, subject_id, _utc_iso(), _json(details or {})),
        )

    def ensure_organization(self, *, org_id: str, owner_user_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        oid = str(org_id or "").strip()
        uid = str(owner_user_id or "").strip()
        if not oid or not uid:
            raise ValueError("org_id and owner_user_id are required")
        connection = self._connect()
        try:
            with self._lock, connection:
                existing = connection.execute("SELECT * FROM organizations WHERE org_id = ?", (oid,)).fetchone()
                if existing is None:
                    now = _utc_iso()
                    connection.execute(
                        "INSERT INTO organizations VALUES (?, ?, ?, ?, '{}')",
                        (oid, str(name or oid), uid, now),
                    )
                    connection.execute(
                        "INSERT INTO org_members VALUES (?, ?, 'owner', '[]', 'active', ?)",
                        (oid, uid, now),
                    )
                    self._audit(connection, org_id=oid, actor=uid, action="organization.created", subject_type="organization", subject_id=oid)
                organization = connection.execute("SELECT * FROM organizations WHERE org_id = ?", (oid,)).fetchone()
            return self._row(organization) or {}
        finally:
            self._close(connection)

    def membership(self, *, org_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        connection = self._connect()
        try:
            with self._lock:
                row = connection.execute(
                    "SELECT * FROM org_members WHERE org_id = ? AND user_id = ? AND status = 'active'",
                    (org_id, user_id),
                ).fetchone()
            return self._row(row)
        finally:
            self._close(connection)

    def require_access(self, *, org_id: str, user_id: str, write: bool = False, admin: bool = False) -> Dict[str, Any]:
        membership = self.membership(org_id=org_id, user_id=user_id)
        if membership is None:
            raise PermissionError("user is not an active member of this organization")
        role = str(membership.get("role") or "reader")
        if admin and role not in ADMIN_ROLES:
            raise PermissionError("organization administrator access is required")
        if write and role not in WRITE_ROLES:
            raise PermissionError("organization write access is required")
        return membership

    def upsert_member(self, *, org_id: str, actor_user_id: str, user_id: str, role: str, audiences: Optional[List[str]] = None) -> Dict[str, Any]:
        self.require_access(org_id=org_id, user_id=actor_user_id, admin=True)
        normalized_role = str(role or "reader").strip().lower()
        if normalized_role not in MEMBER_ROLES:
            raise ValueError(f"unsupported organization role: {normalized_role}")
        connection = self._connect()
        try:
            with self._lock, connection:
                connection.execute(
                    """
                    INSERT INTO org_members (org_id, user_id, role, audiences_json, status, joined_at)
                    VALUES (?, ?, ?, ?, 'active', ?)
                    ON CONFLICT(org_id, user_id) DO UPDATE SET
                        role = excluded.role,
                        audiences_json = excluded.audiences_json,
                        status = 'active'
                    """,
                    (org_id, user_id, normalized_role, _json(audiences or []), _utc_iso()),
                )
                self._audit(connection, org_id=org_id, actor=actor_user_id, action="member.upserted", subject_type="member", subject_id=user_id, details={"role": normalized_role})
            return self.membership(org_id=org_id, user_id=user_id) or {}
        finally:
            self._close(connection)

    def list_members(self, *, org_id: str, user_id: str) -> List[Dict[str, Any]]:
        self.require_access(org_id=org_id, user_id=user_id)
        connection = self._connect()
        try:
            with self._lock:
                rows = connection.execute(
                    "SELECT * FROM org_members WHERE org_id = ? ORDER BY joined_at, user_id", (org_id,)
                ).fetchall()
            return [self._row(row) or {} for row in rows]
        finally:
            self._close(connection)

    def create_revision(
        self,
        *,
        org_id: str,
        user_id: str,
        source_name: str,
        title: str,
        source_text: str,
        metadata: Optional[Dict[str, Any]],
        require_review: bool,
    ) -> Dict[str, Any]:
        self.require_access(org_id=org_id, user_id=user_id, write=True)
        digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        now = _utc_iso()
        connection = self._connect()
        try:
            with self._lock, connection:
                document = connection.execute(
                    "SELECT * FROM org_documents WHERE org_id = ? AND source_name = ?", (org_id, source_name)
                ).fetchone()
                if document is None:
                    document_id = f"org_doc_{uuid.uuid4().hex}"
                    connection.execute(
                        "INSERT INTO org_documents VALUES (?, ?, ?, ?, 0, 'active', ?, ?, ?, ?)",
                        (document_id, org_id, title, source_name, user_id, now, now, _json(metadata or {})),
                    )
                    revision_number = 1
                else:
                    document_id = str(document["document_id"])
                    duplicate = connection.execute(
                        "SELECT * FROM org_document_revisions WHERE document_id = ? AND content_sha256 = ?",
                        (document_id, digest),
                    ).fetchone()
                    if duplicate is not None:
                        return {**(self._row(duplicate) or {}), "document_id": document_id, "duplicate": True}
                    revision_number = int(document["current_revision"] or 0) + 1
                revision_id = f"org_rev_{uuid.uuid4().hex}"
                status = "pending" if require_review else "published"
                connection.execute(
                    "INSERT INTO org_document_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (revision_id, document_id, revision_number, digest, source_text, status, user_id, now, None, None, _json(metadata or {})),
                )
                connection.execute(
                    "UPDATE org_documents SET title = ?, current_revision = ?, updated_at = ?, metadata_json = ? WHERE document_id = ?",
                    (title, revision_number, now, _json(metadata or {}), document_id),
                )
                self._audit(connection, org_id=org_id, actor=user_id, action="document.revision_created", subject_type="revision", subject_id=revision_id, details={"document_id": document_id, "status": status, "sha256": digest})
            return {
                "document_id": document_id,
                "revision_id": revision_id,
                "revision_number": revision_number,
                "content_sha256": digest,
                "status": status,
                "duplicate": False,
            }
        finally:
            self._close(connection)

    def add_knowledge_items(self, *, org_id: str, document_id: str, revision_id: str, rows: Iterable[Dict[str, Any]], status: str) -> List[Dict[str, Any]]:
        now = _utc_iso()
        inserted: List[Dict[str, Any]] = []
        connection = self._connect()
        try:
            with self._lock, connection:
                for row in rows:
                    concept = str(row.get("concept") or "").strip()
                    expression = str(row.get("expression") or "").strip()
                    if not concept or not expression:
                        continue
                    fingerprint = "|".join((org_id, revision_id, concept, expression, str(row.get("audience") or ""), str(row.get("register") or "")))
                    item_id = "org_item_" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
                    item = {
                        "item_id": item_id,
                        "org_id": org_id,
                        "document_id": document_id,
                        "revision_id": revision_id,
                        "concept": concept,
                        "expression": expression,
                        "knowledge_kind": str(row.get("knowledge_kind") or "fact"),
                        "audience": str(row.get("audience") or ""),
                        "register": str(row.get("register") or ""),
                        "terms": [str(value) for value in (row.get("terms_locked") or []) if str(value).strip()],
                        "confidence": float(row.get("confidence") or 0.5),
                        "status": status,
                        "created_at": now,
                    }
                    connection.execute(
                        "INSERT OR REPLACE INTO org_knowledge_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (item_id, org_id, document_id, revision_id, concept, expression, item["knowledge_kind"], item["audience"], item["register"], _json(item["terms"]), item["confidence"], status, now),
                    )
                    inserted.append(item)
            return inserted
        finally:
            self._close(connection)

    def review_revision(self, *, org_id: str, user_id: str, revision_id: str, approve: bool) -> Dict[str, Any]:
        self.require_access(org_id=org_id, user_id=user_id, admin=True)
        connection = self._connect()
        try:
            with self._lock, connection:
                row = connection.execute(
                    """
                    SELECT r.*, d.org_id FROM org_document_revisions r
                    JOIN org_documents d ON d.document_id = r.document_id
                    WHERE r.revision_id = ? AND d.org_id = ?
                    """,
                    (revision_id, org_id),
                ).fetchone()
                if row is None:
                    raise KeyError("organization document revision not found")
                status = "published" if approve else "rejected"
                now = _utc_iso()
                connection.execute(
                    "UPDATE org_document_revisions SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE revision_id = ?",
                    (status, user_id, now, revision_id),
                )
                connection.execute("UPDATE org_knowledge_items SET status = ? WHERE revision_id = ?", (status, revision_id))
                if approve:
                    connection.execute(
                        """
                        UPDATE org_document_revisions SET status = 'superseded'
                        WHERE document_id = ? AND revision_id <> ? AND status = 'published'
                        """,
                        (str(row["document_id"]), revision_id),
                    )
                    connection.execute(
                        """
                        UPDATE org_knowledge_items SET status = 'superseded'
                        WHERE document_id = ? AND revision_id <> ? AND status = 'published'
                        """,
                        (str(row["document_id"]), revision_id),
                    )
                self._audit(connection, org_id=org_id, actor=user_id, action=f"revision.{status}", subject_type="revision", subject_id=revision_id)
            return {"revision_id": revision_id, "document_id": str(row["document_id"]), "status": status}
        finally:
            self._close(connection)

    def revision_items(self, *, org_id: str, user_id: str, revision_id: str) -> List[Dict[str, Any]]:
        self.require_access(org_id=org_id, user_id=user_id)
        connection = self._connect()
        try:
            with self._lock:
                rows = connection.execute(
                    "SELECT * FROM org_knowledge_items WHERE org_id = ? AND revision_id = ? ORDER BY item_id",
                    (org_id, revision_id),
                ).fetchall()
            return [self._row(row) or {} for row in rows]
        finally:
            self._close(connection)

    def list_documents(self, *, org_id: str, user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        self.require_access(org_id=org_id, user_id=user_id)
        connection = self._connect()
        try:
            sql = """
                SELECT d.*, r.revision_id, r.status AS revision_status, r.content_sha256,
                       r.created_at AS revision_created_at, r.reviewed_by, r.reviewed_at
                FROM org_documents d
                LEFT JOIN org_document_revisions r ON r.document_id = d.document_id AND r.revision_number = d.current_revision
                WHERE d.org_id = ?
            """
            params: List[Any] = [org_id]
            if status:
                sql += " AND r.status = ?"
                params.append(status)
            sql += " ORDER BY d.updated_at DESC, d.document_id"
            with self._lock:
                rows = connection.execute(sql, params).fetchall()
            return [self._row(row) or {} for row in rows]
        finally:
            self._close(connection)

    def revoke_document(self, *, org_id: str, user_id: str, document_id: str) -> Dict[str, Any]:
        self.require_access(org_id=org_id, user_id=user_id, admin=True)
        connection = self._connect()
        try:
            with self._lock, connection:
                row = connection.execute(
                    "SELECT document_id FROM org_documents WHERE org_id = ? AND document_id = ?",
                    (org_id, document_id),
                ).fetchone()
                if row is None:
                    raise KeyError("organization document not found")
                now = _utc_iso()
                connection.execute(
                    "UPDATE org_documents SET status = 'revoked', updated_at = ? WHERE document_id = ?",
                    (now, document_id),
                )
                connection.execute(
                    "UPDATE org_document_revisions SET status = 'revoked', reviewed_by = ?, reviewed_at = ? WHERE document_id = ?",
                    (user_id, now, document_id),
                )
                connection.execute("UPDATE org_knowledge_items SET status = 'revoked' WHERE document_id = ?", (document_id,))
                self._audit(connection, org_id=org_id, actor=user_id, action="document.revoked", subject_type="document", subject_id=document_id)
            return {"document_id": document_id, "status": "revoked"}
        finally:
            self._close(connection)

    def list_audit_events(self, *, org_id: str, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        self.require_access(org_id=org_id, user_id=user_id, admin=True)
        connection = self._connect()
        try:
            with self._lock:
                rows = connection.execute(
                    "SELECT * FROM org_audit_events WHERE org_id = ? ORDER BY occurred_at DESC, event_id DESC LIMIT ?",
                    (org_id, max(1, min(int(limit), 500))),
                ).fetchall()
            return [self._row(row) or {} for row in rows]
        finally:
            self._close(connection)

    def recall(self, *, org_id: str, user_id: str, topic: str, audience: str, top_k: int, context_type: str) -> List[Dict[str, Any]]:
        membership = self.require_access(org_id=org_id, user_id=user_id)
        allowed_audiences = {str(value) for value in (membership.get("audiences") or []) if str(value)}
        requested_audience = str(audience or "")
        if allowed_audiences and requested_audience and requested_audience not in allowed_audiences:
            return []
        needle = str(topic or "").strip().casefold()
        connection = self._connect()
        try:
            with self._lock:
                rows = connection.execute(
                    """
                    SELECT k.*, d.source_name, d.title, r.revision_number
                    FROM org_knowledge_items k
                    JOIN org_documents d ON d.document_id = k.document_id
                    JOIN org_document_revisions r ON r.revision_id = k.revision_id
                    WHERE k.org_id = ? AND k.status = 'published'
                    """,
                    (org_id,),
                ).fetchall()
            candidates: List[Dict[str, Any]] = []
            for raw in rows:
                item = self._row(raw) or {}
                item_audience = str(item.get("audience") or "")
                if allowed_audiences and item_audience and item_audience not in allowed_audiences:
                    continue
                haystack = f"{item.get('concept', '')} {item.get('expression', '')}".casefold()
                if needle and needle not in haystack:
                    continue
                audience_hit = bool(requested_audience and item_audience == requested_audience)
                context_hit = bool(context_type and str(item.get("knowledge_kind") or "") in {context_type, "style" if context_type == "writing" else ""})
                item["score"] = float(item.get("confidence") or 0.5) + (0.2 if audience_hit else 0.0) + (0.1 if context_hit else 0.0)
                candidates.append(item)
            candidates.sort(key=lambda row: (-float(row.get("score") or 0), str(row.get("item_id") or "")))
            return candidates[: max(1, int(top_k))]
        finally:
            self._close(connection)

    def published_items(self, *, org_id: str, user_id: str) -> List[Dict[str, Any]]:
        self.require_access(org_id=org_id, user_id=user_id, admin=True)
        connection = self._connect()
        try:
            with self._lock:
                rows = connection.execute(
                    """
                    SELECT k.*, d.source_name, d.title, r.revision_number
                    FROM org_knowledge_items k
                    JOIN org_documents d ON d.document_id = k.document_id
                    JOIN org_document_revisions r ON r.revision_id = k.revision_id
                    WHERE k.org_id = ? AND k.status = 'published'
                    ORDER BY k.document_id, k.item_id
                    """,
                    (org_id,),
                ).fetchall()
            return [self._row(row) or {} for row in rows]
        finally:
            self._close(connection)

    def export_bundle(self, *, org_id: str, user_id: str) -> Dict[str, Any]:
        self.require_access(org_id=org_id, user_id=user_id, admin=True)
        connection = self._connect()
        try:
            tables = {
                "organizations": ("SELECT * FROM organizations WHERE org_id = ?", (org_id,)),
                "members": ("SELECT * FROM org_members WHERE org_id = ? ORDER BY user_id", (org_id,)),
                "documents": ("SELECT * FROM org_documents WHERE org_id = ? ORDER BY document_id", (org_id,)),
                "revisions": (
                    "SELECT r.* FROM org_document_revisions r JOIN org_documents d ON d.document_id = r.document_id WHERE d.org_id = ? ORDER BY r.document_id, r.revision_number",
                    (org_id,),
                ),
                "knowledge_items": ("SELECT * FROM org_knowledge_items WHERE org_id = ? ORDER BY item_id", (org_id,)),
            }
            data: Dict[str, Any] = {}
            with self._lock:
                for name, (sql, params) in tables.items():
                    data[name] = [self._row(row) or {} for row in connection.execute(sql, params).fetchall()]
            manifest = {
                "format": "promethea-org-brain",
                "schema_version": SCHEMA_VERSION,
                "org_id": org_id,
                "exported_at": _utc_iso(),
            }
            checksum_payload = _json({"manifest": manifest, "data": data})
            manifest["content_sha256"] = hashlib.sha256(checksum_payload.encode("utf-8")).hexdigest()
            return {"manifest": manifest, "data": data}
        finally:
            self._close(connection)

    def import_bundle(self, *, bundle: Dict[str, Any], user_id: str, target_org_id: Optional[str] = None) -> Dict[str, Any]:
        manifest = bundle.get("manifest") if isinstance(bundle.get("manifest"), dict) else {}
        data = bundle.get("data") if isinstance(bundle.get("data"), dict) else {}
        if manifest.get("format") != "promethea-org-brain" or int(manifest.get("schema_version") or 0) != SCHEMA_VERSION:
            raise ValueError("unsupported organization brain bundle")
        expected_checksum = str(manifest.get("content_sha256") or "")
        unsigned_manifest = {key: value for key, value in manifest.items() if key != "content_sha256"}
        actual_checksum = hashlib.sha256(_json({"manifest": unsigned_manifest, "data": data}).encode("utf-8")).hexdigest()
        if not expected_checksum or expected_checksum != actual_checksum:
            raise ValueError("organization brain bundle checksum mismatch")
        source_org_id = str(manifest.get("org_id") or "").strip()
        org_id = str(target_org_id or source_org_id).strip()
        if not org_id:
            raise ValueError("organization id is required")
        self.ensure_organization(org_id=org_id, owner_user_id=user_id)
        self.require_access(org_id=org_id, user_id=user_id, admin=True)
        counts = {"documents": 0, "revisions": 0, "knowledge_items": 0}
        id_map: Dict[str, str] = {}
        connection = self._connect()
        try:
            with self._lock, connection:
                for document in data.get("documents") or []:
                    if not isinstance(document, dict):
                        continue
                    old_id = str(document.get("document_id") or "")
                    new_id = old_id if source_org_id == org_id else f"org_doc_{uuid.uuid4().hex}"
                    id_map[old_id] = new_id
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO org_documents
                        (document_id, org_id, title, source_name, current_revision, status, created_by, created_at, updated_at, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (new_id, org_id, str(document.get("title") or document.get("source_name") or new_id), str(document.get("source_name") or new_id), int(document.get("current_revision") or 0), str(document.get("status") or "active"), user_id, str(document.get("created_at") or _utc_iso()), str(document.get("updated_at") or _utc_iso()), _json(document.get("metadata") or {})),
                    )
                    counts["documents"] += 1
                revision_map: Dict[str, str] = {}
                for revision in data.get("revisions") or []:
                    if not isinstance(revision, dict) or str(revision.get("document_id") or "") not in id_map:
                        continue
                    old_revision_id = str(revision.get("revision_id") or "")
                    new_revision_id = old_revision_id if source_org_id == org_id else f"org_rev_{uuid.uuid4().hex}"
                    revision_map[old_revision_id] = new_revision_id
                    connection.execute(
                        "INSERT OR REPLACE INTO org_document_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (new_revision_id, id_map[str(revision.get("document_id"))], int(revision.get("revision_number") or 1), str(revision.get("content_sha256") or ""), str(revision.get("source_text") or ""), str(revision.get("status") or "published"), user_id, str(revision.get("created_at") or _utc_iso()), revision.get("reviewed_by"), revision.get("reviewed_at"), _json(revision.get("metadata") or {})),
                    )
                    counts["revisions"] += 1
                for item in data.get("knowledge_items") or []:
                    if not isinstance(item, dict):
                        continue
                    old_doc_id = str(item.get("document_id") or "")
                    old_revision_id = str(item.get("revision_id") or "")
                    if old_doc_id not in id_map or old_revision_id not in revision_map:
                        continue
                    item_id = str(item.get("item_id") or "") if source_org_id == org_id else f"org_item_{uuid.uuid4().hex}"
                    connection.execute(
                        "INSERT OR REPLACE INTO org_knowledge_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (item_id, org_id, id_map[old_doc_id], revision_map[old_revision_id], str(item.get("concept") or ""), str(item.get("expression") or ""), str(item.get("knowledge_kind") or "fact"), str(item.get("audience") or ""), str(item.get("register") or ""), _json(item.get("terms") or []), float(item.get("confidence") or 0.5), str(item.get("status") or "published"), str(item.get("created_at") or _utc_iso())),
                    )
                    counts["knowledge_items"] += 1
                self._audit(connection, org_id=org_id, actor=user_id, action="bundle.imported", subject_type="organization", subject_id=org_id, details=counts)
            return {"org_id": org_id, **counts}
        finally:
            self._close(connection)

    def stats(self, *, org_id: str, user_id: str) -> Dict[str, Any]:
        membership = self.require_access(org_id=org_id, user_id=user_id)
        connection = self._connect()
        try:
            with self._lock:
                documents = connection.execute("SELECT COUNT(*) FROM org_documents WHERE org_id = ?", (org_id,)).fetchone()[0]
                published = connection.execute("SELECT COUNT(*) FROM org_knowledge_items WHERE org_id = ? AND status = 'published'", (org_id,)).fetchone()[0]
                pending = connection.execute("SELECT COUNT(*) FROM org_document_revisions r JOIN org_documents d ON d.document_id = r.document_id WHERE d.org_id = ? AND r.status = 'pending'", (org_id,)).fetchone()[0]
            return {"documents": int(documents), "published_items": int(published), "pending_revisions": int(pending), "membership": membership}
        finally:
            self._close(connection)
