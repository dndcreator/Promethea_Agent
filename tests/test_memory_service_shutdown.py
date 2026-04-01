from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_memory_service_shutdown_calls_adapter_shutdown():
    from gateway.memory_service import MemoryService

    adapter = MagicMock()
    adapter.is_enabled.return_value = True
    adapter.shutdown.return_value = True

    svc = MemoryService(memory_adapter=adapter)
    ok = await svc.shutdown()
    assert ok is True
    assert adapter.shutdown.call_count == 1


def test_memory_service_sync_stats_includes_pipeline():
    from gateway.memory_service import MemoryService

    adapter = MagicMock()
    adapter.is_enabled.return_value = True
    adapter.get_pipeline_status.return_value = {"raw_log_enabled": True, "raw_log_pending_bytes_estimate": 12}

    svc = MemoryService(memory_adapter=adapter)
    stats = svc.get_sync_stats()
    assert "pipeline" in stats
    assert stats["pipeline"]["raw_log_enabled"] is True
