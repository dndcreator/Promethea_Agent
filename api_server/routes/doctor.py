from __future__ import annotations

from datetime import datetime
import json
import shutil
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

import config as config_module
from .. import state


router = APIRouter()


def _bool_status(ok: bool) -> str:
    return "ok" if ok else "error"


@router.get("/doctor")
async def run_doctor() -> Dict[str, Any]:
    """
    系统自检（Doctor）

    参考 Clawdbot 的 doctor 思路，对当前 Promethea 实例做一次整体体检：
    - 配置是否合理
    - LLM API 是否可用（至少有 key）
    - 记忆系统 / Neo4j 是否按预期启用
    - 插件系统加载情况
    - MCP 工具注册情况
    - 会话存储与指标快照
    """
    checks: Dict[str, Dict[str, Any]] = {}

    cfg = config_module.config

    # 1) 配置与 API 基本检查
    api_ok = True
    api_issues = []
    if not cfg.api.api_key or cfg.api.api_key == "placeholder-key-not-set":
        api_ok = False
        api_issues.append("API_KEY 未配置（使用占位符），LLM 将无法正常工作")

    checks["config_api"] = {
        "ok": api_ok,
        "status": _bool_status(api_ok),
        "api_base_url": cfg.api.base_url,
        "model": cfg.api.model,
        "issues": api_issues,
    }

    # 2) 记忆系统 / Neo4j
    mem_cfg = cfg.memory
    mem_checks: Dict[str, Any] = {
        "enabled": bool(mem_cfg.enabled),
        "neo4j_enabled": bool(mem_cfg.neo4j.enabled),
        "neo4j_uri": mem_cfg.neo4j.uri,
        "warm_layer_enabled": bool(mem_cfg.warm_layer.enabled),
    }

    from core.services import get_memory_service

    mem_ok = True
    mem_issues = []
    try:
        adapter = get_memory_service()
        if mem_cfg.enabled:
            # 开启了记忆系统，但适配器不可用
            if not adapter or not adapter.is_enabled():
                mem_ok = False
                mem_issues.append("记忆系统已在配置中启用，但运行态未就绪（adapter 不可用）")
        else:
            if adapter and adapter.is_enabled():
                mem_issues.append("检测到记忆适配器已启用，但 config.memory.enabled = False")
    except Exception as e:
        mem_ok = False
        mem_issues.append(f"获取记忆服务异常: {e!s}")

    mem_checks["ok"] = mem_ok
    mem_checks["status"] = _bool_status(mem_ok)
    mem_checks["issues"] = mem_issues
    checks["memory"] = mem_checks

    # 3) 插件系统（extensions）
    from core.plugins.runtime import get_active_plugin_registry

    reg = get_active_plugin_registry()
    if reg is None:
        plugins_ok = False
        plugins_info: Dict[str, Any] = {
            "ok": False,
            "status": "error",
            "plugins_total": 0,
            "channels_total": 0,
            "services_total": 0,
            "issues": ["插件注册表未初始化（可能网关尚未加载 extensions）"],
        }
    else:
        plugins_ok = True
        error_plugins = [p.id for p in reg.plugins if p.status == "error"]
        disabled_plugins = [p.id for p in reg.plugins if not p.enabled]
        issues = []
        if error_plugins:
            plugins_ok = False
            issues.append(f"存在初始化失败的插件: {', '.join(error_plugins)}")
        plugins_info = {
            "ok": plugins_ok,
            "status": _bool_status(plugins_ok),
            "plugins_total": len(reg.plugins),
            "channels_total": len(reg.channels),
            "services_total": len(reg.services),
            "error_plugins": error_plugins,
            "disabled_plugins": disabled_plugins,
            "issues": issues,
        }
    checks["plugins"] = plugins_info

    # 4) MCP 服务与工具
    from agentkit.mcp.mcpregistry import MCP_REGISTRY, MANIFEST_CACHE

    mcp_services = list(MCP_REGISTRY.keys())
    mcp_ok = True
    mcp_issues = []
    if not mcp_services:
        mcp_issues.append("未发现已注册的 MCP 服务（如果你没有用 MCP，可以忽略）")
    mcp_info = {
        "ok": mcp_ok,
        "status": _bool_status(mcp_ok),
        "services_total": len(mcp_services),
        "services": mcp_services,
        "manifests_cached": len(MANIFEST_CACHE),
        "issues": mcp_issues,
    }
    checks["mcp"] = mcp_info

    # 5) 会话与存储
    from ..message_manager import message_manager

    sessions_count = len(message_manager.session)
    sessions_path = Path(__file__).resolve().parents[1] / "sessions.json"
    sessions_ok = True
    sessions_issues = []
    sessions_info = {
        "ok": sessions_ok,
        "status": _bool_status(sessions_ok),
        "sessions_in_memory": sessions_count,
        "sessions_file": str(sessions_path),
        "sessions_file_exists": sessions_path.exists(),
        "issues": sessions_issues,
    }
    checks["sessions"] = sessions_info

    # 6) 性能指标快照
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

    # 7) 环境信息
    import platform

    env_info = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    checks["environment"] = {"ok": True, "status": "ok", "details": env_info}

    # 计算总体状态
    overall_ok = all(ch.get("ok", True) for ch in checks.values())
    overall_status = "ok" if overall_ok else "degraded"

    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "checks": checks,
    }


@router.post("/doctor/migrate-config")
async def migrate_config() -> Dict[str, Any]:
    """
    修复 / 迁移配置（Doctor-only migrations）

    设计思路（参考 Clawdbot 的做法）：
    - 不在每次启动时“偷偷”改动配置，而是通过显式的 doctor 命令来迁移；
    - 使用当前版本的 PrometheaConfig 作为“单一真相来源”，把结构写回 config.json；
    - 在写回前，尽量避免把敏感信息（API Key / 密码）落盘。
    """
    cfg = config_module.load_config()
    data = cfg.model_dump()

    # 1) 清洗敏感字段，避免把 secrets 写入 config.json
    try:
        if data.get("api", {}).get("api_key"):
            # 使用占位符代替真实密钥，提示用户通过环境变量/.env 配置
            data["api"]["api_key"] = "placeholder-key-not-set"
    except Exception:
        pass

    try:
        if data.get("memory", {}).get("neo4j", {}).get("password"):
            data["memory"]["neo4j"]["password"] = ""
    except Exception:
        pass

    # 优先使用 config/default.json，如果不存在则使用根目录的 config.json（向后兼容）
    config_path = Path("config/default.json")
    if not config_path.exists():
        config_path = Path("config.json")
    
    backup_path: Path | None = None

    # 2) 如有旧配置，先做备份
    if config_path.exists():
        try:
            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            backup_path = config_path.with_suffix(f".json.bak.{ts}")
            shutil.copy2(config_path, backup_path)
        except Exception:
            # 备份失败不应阻止迁移继续执行
            backup_path = None

    # 3) 确保 config/ 目录存在
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # 4) 写回新的配置文件（结构对齐当前版本）
    try:
        with config_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        return {
            "status": "error",
            "message": f"写入配置文件失败: {e}",
            "config_path": str(config_path),
            "backup": str(backup_path) if backup_path else None,
        }

    # 4) 重新加载全局配置对象（行为与 /config 更新时保持一致）
    try:
        new_cfg = config_module.load_config()
        config_module.config = new_cfg  # type: ignore[attr-defined]
    except Exception as e:
        return {
            "status": "warning",
            "message": f"配置已写入，但重新加载失败: {e}",
            "config_path": str(config_path),
            "backup": str(backup_path) if backup_path else None,
        }

    return {
        "status": "success",
        "message": f"配置已根据当前版本结构迁移并写入 {config_path}（敏感字段已被占位/清除）。",
        "config_path": str(config_path),
        "backup": str(backup_path) if backup_path else None,
    }

