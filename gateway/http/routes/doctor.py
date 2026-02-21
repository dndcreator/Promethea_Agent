from __future__ import annotations

import json
import platform
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

import config as config_module
from .. import state
from ..dispatcher import get_gateway_server


router = APIRouter()


def _bool_status(ok: bool) -> str:
    return "ok" if ok else "error"


@router.get("/doctor")
async def run_doctor() -> Dict[str, Any]:
    checks: Dict[str, Dict[str, Any]] = {}
    cfg = config_module.config
    gateway_server = get_gateway_server()

    api_ok = bool(cfg.api.api_key and cfg.api.api_key != "placeholder-key-not-set")
    checks["config_api"] = {
        "ok": api_ok,
        "status": _bool_status(api_ok),
        "api_base_url": cfg.api.base_url,
        "model": cfg.api.model,
        "issues": [] if api_ok else ["API key not configured"],
    }

    mem_ok = True
    mem_issues = []
    try:
        memory_service = gateway_server.memory_service
        if cfg.memory.enabled and (not memory_service or not memory_service.is_enabled()):
            mem_ok = False
            mem_issues.append("memory enabled in config but gateway memory service is unavailable")
    except Exception as e:
        mem_ok = False
        mem_issues.append(f"memory check failed: {e}")

    checks["memory"] = {
        "ok": mem_ok,
        "status": _bool_status(mem_ok),
        "enabled": bool(cfg.memory.enabled),
        "neo4j_enabled": bool(cfg.memory.neo4j.enabled),
        "neo4j_uri": cfg.memory.neo4j.uri,
        "warm_layer_enabled": bool(cfg.memory.warm_layer.enabled),
        "issues": mem_issues,
    }

    from core.plugins.runtime import get_active_plugin_registry

    reg = get_active_plugin_registry()
    if reg is None:
        checks["plugins"] = {
            "ok": False,
            "status": "error",
            "plugins_total": 0,
            "channels_total": 0,
            "services_total": 0,
            "issues": ["plugin registry not initialized"],
        }
    else:
        error_plugins = [p.id for p in reg.plugins if p.status == "error"]
        checks["plugins"] = {
            "ok": not error_plugins,
            "status": _bool_status(not error_plugins),
            "plugins_total": len(reg.plugins),
            "channels_total": len(reg.channels),
            "services_total": len(reg.services),
            "error_plugins": error_plugins,
            "disabled_plugins": [p.id for p in reg.plugins if not p.enabled],
            "issues": [f"error plugins: {', '.join(error_plugins)}"] if error_plugins else [],
        }

    from agentkit.mcp.mcpregistry import MANIFEST_CACHE, MCP_REGISTRY

    checks["mcp"] = {
        "ok": True,
        "status": "ok",
        "services_total": len(MCP_REGISTRY),
        "services": list(MCP_REGISTRY.keys()),
        "manifests_cached": len(MANIFEST_CACHE),
        "issues": [],
    }

    checks["sessions"] = {
        "ok": True,
        "status": "ok",
        "sessions_in_memory": (
            len(gateway_server.message_manager.session)
            if gateway_server.message_manager
            else 0
        ),
    }

    try:
        metrics_snapshot = state.metrics.get_stats()
        metrics_ok = True
    except Exception as e:
        metrics_ok = False
        metrics_snapshot = {"error": str(e)}
    checks["metrics"] = {
        "ok": metrics_ok,
        "status": _bool_status(metrics_ok),
        "snapshot": metrics_snapshot,
    }

    checks["gateway"] = {
        "ok": bool(gateway_server.is_running),
        "status": "ok" if gateway_server.is_running else "error",
        "connections": gateway_server.connection_manager.get_active_count(),
        "channels": list(gateway_server.channels.keys()),
    }

    checks["environment"] = {
        "ok": True,
        "status": "ok",
        "details": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
    }

    overall_ok = all(ch.get("ok", True) for ch in checks.values())
    return {
        "status": "ok" if overall_ok else "degraded",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "checks": checks,
    }


@router.post("/doctor/migrate-config")
async def migrate_config() -> Dict[str, Any]:
    cfg = config_module.load_config()
    data = cfg.model_dump()

    # Keep secrets out of config file
    if data.get("api", {}).get("api_key"):
        data["api"]["api_key"] = "placeholder-key-not-set"
    if data.get("memory", {}).get("neo4j", {}).get("password"):
        data["memory"]["neo4j"]["password"] = ""
    if data.get("memory", {}).get("api", {}).get("api_key"):
        data["memory"]["api"]["api_key"] = ""

    config_path = Path("config/default.json")
    if not config_path.exists():
        config_path = Path("config.json")

    backup_path: Path | None = None
    if config_path.exists():
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_path = config_path.with_suffix(f".json.bak.{ts}")
        try:
            shutil.copy2(config_path, backup_path)
        except Exception:
            backup_path = None

    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with config_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        return {
            "status": "error",
            "message": f"failed to write config: {e}",
            "config_path": str(config_path),
            "backup": str(backup_path) if backup_path else None,
        }

    try:
        new_cfg = config_module.load_config()
        config_module.config = new_cfg  # type: ignore[attr-defined]
    except Exception as e:
        return {
            "status": "warning",
            "message": f"config written but reload failed: {e}",
            "config_path": str(config_path),
            "backup": str(backup_path) if backup_path else None,
        }

    return {
        "status": "success",
        "message": f"config migrated to {config_path}; secrets were cleared",
        "config_path": str(config_path),
        "backup": str(backup_path) if backup_path else None,
    }


