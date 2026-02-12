from __future__ import annotations

from fastapi import APIRouter

from .. import state


router = APIRouter()


@router.get("/metrics")
async def get_metrics():
    """Get runtime metrics."""
    return {"status": "success", "metrics": state.metrics.get_stats()}
