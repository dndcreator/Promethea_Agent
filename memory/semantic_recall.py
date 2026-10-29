"""Optional semantic retrieval and bounded background indexing, owned by memory."""
from __future__ import annotations

import threading

from config import PROJECT_ROOT, MemoryEmbeddingConfig
from memory.embedding import EmbeddingEncoder, EmbeddingUnavailable, fingerprint


class SemanticRecall:
    def __init__(self, index, *, settings_for_user, cache_dir: str):
        self.index = index
        self.settings_for_user = settings_for_user
        self.encoder = EmbeddingEncoder(PROJECT_ROOT / cache_dir)
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker = None
        self._users: dict[str, dict] = {}
        self._downloads: dict[str, MemoryEmbeddingConfig] = {}
        self._warmups: dict[str, str] = {}
        self._busy = threading.Lock()

    def _settings(self, user_id: str) -> MemoryEmbeddingConfig:
        return MemoryEmbeddingConfig(**self.settings_for_user(user_id))

    def start(self) -> None:
        with self._lock:
            if self._worker is None and not self._stop.is_set():
                self._worker = threading.Thread(target=self._run, name="memory-semantic-index", daemon=True)
                self._worker.start()

    def status(self, user_id: str) -> dict:
        settings = self._settings(user_id)
        supported = self.index is not None
        with self._lock:
            state = self._users.setdefault(user_id, {})
            identity = fingerprint(settings)
            if state.get("identity") != identity:
                state.clear()
                state.update(identity=identity, index_state="idle", indexed=0, total=0, reason=None)
            model_state = "disabled" if settings.provider == "disabled" else (
                self.encoder.local_state(settings) if settings.provider == "local" else "configured")
            if user_id in self._downloads and fingerprint(self._downloads[user_id]) == identity:
                model_state = "downloading"
            return {"provider": settings.provider, "model": settings.model, "revision": settings.revision,
                    "model_state": model_state, "supported": supported,
                    "index_state": state.get("index_state", "idle") if supported else "unsupported",
                    "indexed": state.get("indexed", 0), "total": state.get("total", 0),
                    "reason": state.get("reason"), "fallback": "keyword_graph"}

    def request_sync(self, user_id: str, *, download: bool = False) -> dict:
        current = self.status(user_id)
        if download:
            if current["provider"] != "local":
                raise ValueError("local_provider_required")
            if current["model_state"] == "missing_dependencies":
                raise ValueError("missing_dependencies")
            with self._lock:
                self._downloads[user_id] = self._settings(user_id)
        self.start()
        self._wake.set()
        return self.status(user_id)

    def search(self, user_id: str, query: str, limit: int) -> list[dict]:
        if not query.strip():
            return []
        state = self.status(user_id)
        if state["provider"] == "disabled" or not state["supported"]:
            return []
        self.start()
        if not state["indexed"] or state["index_state"] == "failed" or not self._busy.acquire(blocking=False):
            return []
        settings = self._settings(user_id)
        try:
            if settings.provider == "local" and not self.encoder.is_loaded(settings):
                if self.encoder.local_state(settings) == "ready":
                    with self._lock:
                        self._warmups[user_id] = query
                    self._wake.set()
                return []
            vector = self.encoder.encode([query], settings)[0]
            return self.index.search(user_id, fingerprint(settings), vector, limit, settings.min_similarity)
        except Exception as error:
            self._failure(user_id, error)
            return []
        finally:
            self._busy.release()

    def _failure(self, user_id: str, error: Exception) -> None:
        reason = str(error) if isinstance(error, EmbeddingUnavailable) else "embedding_unavailable"
        with self._lock:
            self._users[user_id].update(index_state="failed", reason=reason)

    def sync_once(self, user_id: str) -> None:
        self.status(user_id)
        settings = self._settings(user_id)
        identity = fingerprint(settings)
        if settings.provider == "disabled" or self.index is None or self._stop.is_set():
            return
        if not self._busy.acquire(blocking=False):
            return
        try:
            with self._lock:
                self._users[user_id].update(index_state="indexing", reason=None)
            rows = self.index.pending(user_id, identity, settings.batch_size)
            if rows:
                vectors = self.encoder.encode([row["content"] for row in rows], settings)
                if self._stop.is_set() or fingerprint(self._settings(user_id)) != identity:
                    return
                self.index.write(user_id, identity, rows, vectors)
            counts = self.index.counts(user_id, identity)
            if fingerprint(self._settings(user_id)) != identity:
                return
            ready = counts["indexed"] == counts["total"] and (not counts["total"] or self.index.is_online(user_id, identity))
            if ready and not self._users[user_id].get("pruned"):
                pruned = self.index.prune(user_id, identity)
                with self._lock:
                    self._users[user_id]["pruned"] = pruned
            with self._lock:
                if self._users[user_id].get("identity") == identity:
                    self._users[user_id].update(**counts, index_state="ready" if ready else "indexing")
            self.encoder.unload_if_idle(settings.idle_unload_s)
        except Exception as error:
            self._failure(user_id, error)
        finally:
            self._busy.release()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(2)
            self._wake.clear()
            with self._lock:
                users = list(self._users)
                downloads = dict(self._downloads)
                warmups = self._warmups
                self._warmups = {}
            for user_id in users:
                if self._stop.is_set():
                    return
                try:
                    if user_id in downloads:
                        settings = self._settings(user_id)
                        if fingerprint(settings) == fingerprint(downloads[user_id]) and settings.provider == "local":
                            self.encoder.download(settings)
                        with self._lock:
                            self._downloads.pop(user_id, None)
                    if user_id in warmups:
                        settings = self._settings(user_id)
                        if settings.provider == "local":
                            self.encoder.encode([warmups[user_id]], settings)
                    self.sync_once(user_id)
                    self.encoder.unload_if_idle(self._settings(user_id).idle_unload_s)
                except Exception as error:
                    with self._lock:
                        self._downloads.pop(user_id, None)
                    self._failure(user_id, error)
            # Reconciliation is derived from actual content, so restart never loses jobs.
            with self._lock:
                pending = any(row.get("index_state") == "indexing" for row in self._users.values())
            self._wake.wait(3 if pending else 27)

    def stop(self, timeout_s: float = 5) -> bool:
        self._stop.set()
        self._wake.set()
        if self._worker:
            self._worker.join(timeout_s)
        self.encoder.unload_if_idle(0)
        return self._worker is None or not self._worker.is_alive()
