"""Optional embedding I/O. Importing memory never imports a model runtime."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


class EmbeddingUnavailable(RuntimeError):
    pass


def fingerprint(settings) -> str:
    identity = [settings.provider, settings.model, settings.revision,
                settings.base_url.rstrip("/"), "normalized-v1"]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]


def validate_vectors(vectors, count: int) -> list[list[float]]:
    rows = [[float(value) for value in row] for row in vectors]
    if len(rows) != count or not rows or not rows[0] or len(rows[0]) > 4096:
        raise EmbeddingUnavailable("invalid_embedding_response")
    dimension = len(rows[0])
    for row in rows:
        if len(row) != dimension or not all(math.isfinite(value) for value in row):
            raise EmbeddingUnavailable("invalid_embedding_response")
        norm = math.sqrt(sum(value * value for value in row))
        if norm == 0:
            raise EmbeddingUnavailable("invalid_embedding_response")
        row[:] = [value / norm for value in row]
    return rows


class EmbeddingEncoder:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self._model = None
        self._identity = ""
        self._last_used = 0.0

    def path(self, settings) -> Path:
        key = hashlib.sha256(f"{settings.model}@{settings.revision}".encode()).hexdigest()
        return self.cache_dir / key

    def local_state(self, settings) -> str:
        if importlib.util.find_spec("sentence_transformers") is None:
            return "missing_dependencies"
        return "ready" if (self.path(settings) / ".complete").is_file() else "missing_model"

    def is_loaded(self, settings) -> bool:
        return self._model is not None and self._identity == fingerprint(settings)

    def download(self, settings) -> None:
        if importlib.util.find_spec("sentence_transformers") is None:
            raise EmbeddingUnavailable("missing_dependencies")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", settings.model) or not re.fullmatch(r"[0-9a-f]{40}", settings.revision):
            raise EmbeddingUnavailable("pinned_model_revision_required")
        from huggingface_hub import HfApi, snapshot_download

        # Only safe tensor weights and data/config files; never Python or pickle.
        info = HfApi(token=False).model_info(settings.model, revision=settings.revision, files_metadata=True, timeout=20)
        files = [file for file in info.siblings if file.rfilename.endswith((".json", ".txt", ".safetensors"))
                 and not file.rfilename.startswith(("onnx/", "openvino/"))]
        if not any(file.rfilename.endswith(".safetensors") for file in files):
            raise EmbeddingUnavailable("safetensors_required")
        if any(file.size is None for file in files) or sum(file.size for file in files) > settings.max_download_mb * 1024 * 1024:
            raise EmbeddingUnavailable("download_limit_exceeded")
        target = self.path(settings)
        snapshot_download(settings.model, revision=settings.revision, local_dir=target,
                          allow_patterns=[file.rfilename for file in files], max_workers=2, token=False)
        (target / ".complete").touch()

    def encode(self, texts: list[str], settings) -> list[list[float]]:
        if not self._lock.acquire(blocking=False):
            raise EmbeddingUnavailable("encoder_busy")
        try:
            if settings.provider == "local":
                state = self.local_state(settings)
                if state != "ready":
                    raise EmbeddingUnavailable(state)
                identity = fingerprint(settings)
                if self._model is None or self._identity != identity:
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(str(self.path(settings)), device="cpu",
                                                      local_files_only=True, trust_remote_code=False,
                                                      model_kwargs={"use_safetensors": True})
                    self._identity = identity
                values = self._model.encode(texts, batch_size=settings.batch_size,
                                            normalize_embeddings=True, show_progress_bar=False)
                self._last_used = time.monotonic()
                return validate_vectors(values, len(texts))
            if settings.provider == "openai-compatible":
                url = urlsplit(settings.base_url)
                if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise EmbeddingUnavailable("invalid_provider_url")
                import httpx
                from openai import OpenAI
                # Endpoint is operator-configured; no redirects or ambient proxies.
                with OpenAI(base_url=settings.base_url, api_key=settings.api_key or "local",
                            max_retries=0, timeout=settings.timeout_s,
                            http_client=httpx.Client(trust_env=False, follow_redirects=False)) as client:
                    result = client.embeddings.create(model=settings.model, input=texts)
                    data = sorted(result.data, key=lambda item: item.index)
                    if [item.index for item in data] != list(range(len(texts))):
                        raise EmbeddingUnavailable("invalid_embedding_response")
                    return validate_vectors([item.embedding for item in data], len(texts))
            raise EmbeddingUnavailable("disabled")
        finally:
            self._lock.release()

    def unload_if_idle(self, seconds: int) -> None:
        if self._lock.acquire(blocking=False):
            try:
                if self._model is not None and time.monotonic() - self._last_used >= seconds:
                    self._model = None
                    self._identity = ""
            finally:
                self._lock.release()
