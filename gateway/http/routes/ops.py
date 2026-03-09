from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter

from ..dispatcher import get_gateway_server


router = APIRouter()


@router.get("/ops/capabilities")
async def ops_capabilities() -> Dict[str, Any]:
    gateway_server = get_gateway_server()

    config_service = getattr(gateway_server, "config_service", None)
    merged = config_service.get_merged_config(None) if config_service else {}
    sandbox_cfg = (merged.get("sandbox") or {}) if isinstance(merged, dict) else {}
    reasoning_cfg = (merged.get("reasoning") or {}) if isinstance(merged, dict) else {}
    memory_cfg = (merged.get("memory") or {}) if isinstance(merged, dict) else {}

    plugin_runtime = getattr(gateway_server, "plugin_runtime", None)
    plugin_count = len(getattr(plugin_runtime, "plugins", []) or []) if plugin_runtime else None

    return {
        "status": "success",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "capabilities": {
            "automation_triggers": ["/api/automation/webhook", "/api/automation/cron/wakeup"],
            "skills_catalog": "/api/skills/catalog",
            "voice_turn": "/api/voice/turn",
            "model_failover": True,
            "sandbox_enabled": bool(sandbox_cfg.get("enabled", False)),
            "reasoning_enabled": bool(reasoning_cfg.get("enabled", False)),
            "memory_enabled": bool(memory_cfg.get("enabled", False)),
            "plugins_loaded": plugin_count,
        },
    }


@router.get("/ops/runbook")
async def ops_runbook() -> Dict[str, Any]:
    return {
        "status": "success",
        "runbook": [
            "1) Check /api/status for service health.",
            "2) Check /api/ops/capabilities for feature toggles.",
            "3) If chat errors occur, validate /api/config runtime and API key.",
            "4) If memory errors occur, verify Neo4j and memory flags.",
            "5) For automation calls, verify AUTOMATION__TOKEN header.",
        ],
    }
