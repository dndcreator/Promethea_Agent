import os
import threading
import time
from pathlib import Path

import pytest

from memory.adapter import MemoryAdapter


pytestmark = [
    pytest.mark.stress,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("RUN_STRESS_TESTS", "").strip().lower() not in {"1", "true", "yes"},
        reason="Stress tests are opt-in. Set RUN_STRESS_TESTS=1 to run.",
    ),
]


class _CountingStore:
    def __init__(self) -> None:
        self.count = 0
        self._lock = threading.Lock()

    def add_message(self, **kwargs):  # noqa: ANN003 - test double
        _ = kwargs
        with self._lock:
            self.count += 1
        return True


def _build_stress_adapter(tmp_path: Path) -> tuple[MemoryAdapter, _CountingStore]:
    adapter = MemoryAdapter.__new__(MemoryAdapter)
    store = _CountingStore()
    adapter.enabled = True
    adapter.store_backend = "flat_memory"
    adapter.store = store
    adapter.hot_layer = None
    adapter._dual_write_store = None
    adapter._hot_layer_lock = threading.Lock()
    adapter._raw_log_enabled = True
    adapter._raw_log_defer_hot_write = True
    adapter._raw_log_flush_interval_s = 0.2
    adapter._raw_log_max_batch_size = 128
    adapter._raw_log_path = str(tmp_path / "raw_log.jsonl")
    adapter._raw_log_state_path = str(tmp_path / "raw_log.state.json")
    adapter._raw_log_lock = threading.Lock()
    adapter._raw_log_replay_lock = threading.Lock()
    adapter._raw_log_wakeup_event = threading.Event()
    adapter._raw_log_stop_event = threading.Event()
    adapter._raw_log_state = {"last_offset": 0, "last_entry_id": "", "updated_at": 0.0}
    adapter._on_message_saved_after_store = lambda *args, **kwargs: None
    return adapter, store


def test_memory_raw_log_stress_bulk_append_and_flush(tmp_path):
    adapter, store = _build_stress_adapter(tmp_path)
    total = 3000

    start = time.perf_counter()
    for i in range(total):
        ok = adapter.add_message(
            session_id="s-bulk",
            role="user",
            content=f"bulk-message-{i}",
            user_id="u-stress",
            metadata={"idx": i},
        )
        assert ok is True
    append_elapsed = time.perf_counter() - start

    flushed = adapter.flush_raw_log(timeout_s=20.0)
    assert flushed is True
    assert store.count == total
    status = adapter.get_pipeline_status()
    assert status["raw_log_pending_bytes_estimate"] == 0
    assert append_elapsed < 10.0


def test_memory_raw_log_stress_concurrent_append_and_flush(tmp_path):
    adapter, store = _build_stress_adapter(tmp_path)
    workers = 8
    each = 400
    total = workers * each
    barrier = threading.Barrier(workers)
    errors = []
    errors_lock = threading.Lock()

    def _writer(worker_id: int) -> None:
        try:
            barrier.wait(timeout=5.0)
            for j in range(each):
                ok = adapter.add_message(
                    session_id=f"s-{worker_id}",
                    role="user",
                    content=f"w{worker_id}-m{j}",
                    user_id=f"u-{worker_id}",
                    metadata={"worker": worker_id, "idx": j},
                )
                if not ok:
                    raise RuntimeError(f"append failed: worker={worker_id}, idx={j}")
        except Exception as exc:  # pragma: no cover - defensive in stress path
            with errors_lock:
                errors.append(str(exc))

    threads = [threading.Thread(target=_writer, args=(i,), daemon=True) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
        assert not t.is_alive()
    assert not errors

    flushed = adapter.flush_raw_log(timeout_s=30.0)
    assert flushed is True
    assert store.count == total
    status = adapter.get_pipeline_status()
    assert status["raw_log_pending_bytes_estimate"] == 0


def test_memory_raw_log_stress_resume_from_checkpoint(tmp_path):
    adapter1, store1 = _build_stress_adapter(tmp_path)
    total = 1200
    for i in range(total):
        assert adapter1.add_message(
            session_id="s-resume",
            role="user",
            content=f"resume-{i}",
            user_id="u-resume",
            metadata={"idx": i},
        )

    processed_before_restart = adapter1._replay_raw_log_once(max_records=350)
    assert processed_before_restart == 350
    assert store1.count == 350

    adapter2, store2 = _build_stress_adapter(tmp_path)
    adapter2._raw_log_state = adapter2._load_raw_log_state()
    drained = adapter2.flush_raw_log(timeout_s=30.0)
    assert drained is True
    assert store2.count == total - 350
    status = adapter2.get_pipeline_status()
    assert status["raw_log_pending_bytes_estimate"] == 0
