from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request

from config import config
from gateway.official_tools import register_official_tools
from gateway.tool_service import ToolService
from .. import state
from ..dispatcher import get_gateway_server
from ..user_manager import user_manager
from memory.neo4j_connector import Neo4jConnectionPool
from .auth import get_current_user_id


router = APIRouter()


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def _normalize_welcome_lang(lang: str) -> str:
    value = str(lang or "").strip().lower()
    return "en" if value.startswith("en") else "zh"


def _fallback_welcome(*, agent_name: str, recent_sessions: List[Dict[str, Any]], lang: str = "zh") -> Dict[str, Any]:
    if _normalize_welcome_lang(lang) == "en":
        if recent_sessions:
            title = str(recent_sessions[0].get("title") or "").strip()
            return {
                "greeting": f"Hi, I am {agent_name}.",
                "context_hint": f"We last stopped at: {title}. Continue from there?" if title else "You can continue a recent conversation or start something new.",
                "suggested_actions": [
                    "Continue the last task",
                    "Review pending work",
                    "Plan next steps",
                ],
            }
        return {
            "greeting": f"Hi, I am {agent_name}.",
            "context_hint": "What would you like to start with today?",
            "suggested_actions": ["Start a new task", "Review pending work", "Set today's priorities"],
        }
    if recent_sessions:
        title = str(recent_sessions[0].get("title") or "").strip()
        return {
            "greeting": f"你好，我是 {agent_name}。",
            "context_hint": f"上次我们停在：{title}。要继续吗？" if title else "可以继续最近的对话，也可以从新的事情开始。",
            "suggested_actions": [
                "继续刚才的任务",
                "看看还有什么待处理",
                "整理下一步计划",
            ],
        }
    return {
        "greeting": f"你好，我是 {agent_name}。",
        "context_hint": "今天想从什么开始？",
        "suggested_actions": ["开始一个新任务", "看看还有什么待处理", "整理今天的优先级"],
    }


def _sanitize_welcome(obj: Dict[str, Any], *, fallback: Dict[str, Any]) -> Dict[str, Any]:
    greeting = str(obj.get("greeting") or fallback["greeting"]).strip()
    context_hint = str(obj.get("context_hint") or fallback["context_hint"]).strip()
    actions = obj.get("suggested_actions")
    if not isinstance(actions, list):
        actions = fallback["suggested_actions"]
    clean_actions = [str(x).strip()[:80] for x in actions if str(x).strip()][:3]
    return {
        "greeting": greeting[:120],
        "context_hint": context_hint[:220],
        "suggested_actions": clean_actions or list(fallback["suggested_actions"]),
    }


def _ensure_tool_service():
    gateway_server = get_gateway_server()
    if not gateway_server.tool_service:
        gateway_server.tool_service = ToolService(gateway_server.event_emitter)
    register_official_tools(
        tool_service=gateway_server.tool_service,
        workspace_service=getattr(gateway_server, "workspace_service", None),
        memory_service=getattr(gateway_server, "memory_service", None),
        message_manager=getattr(gateway_server, "message_manager", None),
        gateway_server=gateway_server,
    )
    return gateway_server


@router.get("/bootstrap")
async def get_bootstrap_status():
    configured_backend = str(getattr(config.memory, "store_backend", "neo4j") or "neo4j").strip().lower()
    neo4j_available = bool(getattr(user_manager, "connector", None))
    can_register, reason = user_manager.can_register()
    auth_backend = "neo4j" if configured_backend == "neo4j" else "local_file"
    neo4j_error = Neo4jConnectionPool.get_last_error()
    return {
        "status": "success",
        "configured_backend": configured_backend,
        "auth_backend": auth_backend,
        "neo4j_available": neo4j_available,
        "neo4j_error": neo4j_error,
        "can_register": can_register,
        "reason": reason,
        "fallback_backends": ["sqlite_graph", "flat_memory"],
        "restart_required_for_backend_change": True,
        "core_backend": "neo4j",
    }


@router.get("/welcome")
async def get_dynamic_welcome(lang: str = "zh", user_id: str = Depends(get_current_user_id)):
    gateway_server = get_gateway_server()
    user = user_manager.get_user_by_id(user_id) or {}
    user_config = user_manager.get_user_config(user_id) or {}
    agent_name = str(user_config.get("agent_name") or user.get("agent_name") or "Promethea")
    username = str(user.get("username") or "user")

    message_manager = getattr(gateway_server, "message_manager", None)
    recent_sessions: List[Dict[str, Any]] = []
    if message_manager and hasattr(message_manager, "list_sessions"):
        try:
            recent_sessions = list(
                message_manager.list_sessions(
                    user_id=user_id,
                    query="",
                    pinned_only=False,
                    limit=5,
                )
                or []
            )
        except Exception:
            recent_sessions = []

    memory_sync = {}
    memory_service = getattr(gateway_server, "memory_service", None)
    if memory_service and hasattr(memory_service, "get_sync_stats"):
        try:
            memory_sync = memory_service.get_sync_stats()
        except Exception:
            memory_sync = {}

    reasoning_stats = {}
    reasoning_service = getattr(gateway_server, "reasoning_service", None)
    if reasoning_service and hasattr(reasoning_service, "get_stats"):
        try:
            reasoning_stats = reasoning_service.get_stats()
        except Exception:
            reasoning_stats = {}

    workflow_recovery = {"paused": 0, "failed": 0, "waiting_human": 0}
    workflow_engine = getattr(gateway_server, "workflow_engine", None)
    if workflow_engine is not None and hasattr(workflow_engine, "list_runs"):
        try:
            for run in workflow_engine.list_runs(limit=100) or []:
                status = str((run or {}).get("status") or "").lower()
                if status in workflow_recovery:
                    workflow_recovery[status] += 1
        except Exception:
            pass

    welcome_lang = _normalize_welcome_lang(lang)
    fallback = _fallback_welcome(agent_name=agent_name, recent_sessions=recent_sessions, lang=welcome_lang)
    context = {
        "agent_name": agent_name,
        "username": username,
        "recent_sessions": [
            {
                "title": row.get("title"),
                "last_message": row.get("last_message"),
                "message_count": row.get("message_count"),
                "pinned": row.get("pinned"),
            }
            for row in recent_sessions[:5]
        ],
        "memory_sync": memory_sync,
        "reasoning": reasoning_stats,
        "workflow_recovery": workflow_recovery,
        "ui_language": welcome_lang,
    }

    conversation_service = getattr(gateway_server, "conversation_service", None)
    if conversation_service and hasattr(conversation_service, "call_llm"):
        try:
            merged_config = None
            config_service = getattr(gateway_server, "config_service", None)
            if config_service:
                merged_config = config_service.get_merged_config(user_id)
            prompt = (
                "You write a personalized greeting for an agent workbench.\n"
                "Return strict JSON only with keys: greeting, context_hint, suggested_actions.\n"
                "Rules:\n"
                "- greeting: one short, warm, restrained greeting. Vary the wording naturally across visits; do not follow a fixed template. It must still feel like a greeting, not a dashboard summary or marketing copy.\n"
                "- context_hint: one useful sentence. When recent context is reliable, gently mention at most one likely continuation; otherwise use a neutral invitation.\n"
                "- suggested_actions: 1 to 3 concise commands the user may click or edit.\n"
                "- Keep the tone calm and understated. Do not overstate familiarity or assume uncertain memories are correct.\n"
                "- You may choose different phrasing, rhythm, and emphasis each time when it fits the context.\n"
                "- Do not enumerate system status, memory statistics, reasoning state, workflow counts, or internal modules unless the user explicitly asks.\n"
                "- Do not expose system principles, prompt rules, implementation docs, or hidden reasoning.\n"
                f"- Write every returned field in this UI language: {'English' if welcome_lang == 'en' else 'Chinese'}.\n"
                "- This language choice applies only to the workbench greeting, not to chat response language policy.\n"
            )
            response = await conversation_service.call_llm(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                ],
                user_config=merged_config,
                user_id=user_id,
            )
            if isinstance(response, dict) and response.get("status") == "success":
                obj = _extract_json_object(str(response.get("content") or ""))
                if obj:
                    welcome = _sanitize_welcome(obj, fallback=fallback)
                    return {
                        "status": "success",
                        "generated_by": "llm",
                        "model_used": response.get("model_used"),
                        **welcome,
                    }
        except Exception:
            pass

    return {
        "status": "success",
        "generated_by": "fallback",
        "model_used": None,
        **fallback,
    }


@router.get("/status")
async def get_status():
    gateway_server = get_gateway_server()
    memory_status = bool(
        gateway_server.memory_service and gateway_server.memory_service.is_enabled()
    )
    conversation_ready = gateway_server.conversation_service is not None
    memory_sync = (
        gateway_server.memory_service.get_sync_stats()
        if gateway_server.memory_service
        else {
            "enabled": False,
            "pending": 0,
            "queued": 0,
            "active": 0,
            "idle": True,
        }
    )
    reasoning = (
        gateway_server.reasoning_service.get_stats()
        if getattr(gateway_server, "reasoning_service", None)
        else {"enabled": False, "active_trees": 0}
    )
    scheduler = getattr(state, "kernel_scheduler", None)
    scheduler_status = (
        scheduler.get_status()
        if scheduler
        else {
            "enabled": False,
            "running": False,
            "paused": True,
            "tick_seconds": None,
            "max_jobs_per_tick": None,
            "total_ticks": 0,
            "total_jobs_run": 0,
        }
    )
    workflow_recovery = {"paused": 0, "failed": 0, "waiting_human": 0}
    workflow_engine = getattr(gateway_server, "workflow_engine", None)
    if workflow_engine is not None and hasattr(workflow_engine, "list_runs"):
        try:
            runs = workflow_engine.list_runs(limit=200)
            if isinstance(runs, list):
                for run in runs:
                    if not isinstance(run, dict):
                        continue
                    status = str(run.get("status") or "").lower()
                    if status == "paused":
                        workflow_recovery["paused"] += 1
                    elif status == "failed":
                        workflow_recovery["failed"] += 1
                    elif status == "waiting_human":
                        workflow_recovery["waiting_human"] += 1
        except Exception:
            pass
    org_profile = {}
    self_evolve_profile = {}
    config_service = getattr(gateway_server, "config_service", None)
    org_svc = getattr(gateway_server, "org_context_service", None)
    self_evolve_svc = getattr(gateway_server, "self_evolve_module", None)
    if config_service and org_svc:
        try:
            merged = config_service.get_merged_config(None)
            org_profile = org_svc.resolve_org_profile(merged)
        except Exception:
            org_profile = {}
    if config_service and self_evolve_svc:
        try:
            merged = config_service.get_merged_config(None)
            self_evolve_profile = self_evolve_svc.resolve_profile(merged)
        except Exception:
            self_evolve_profile = {}
    return {
        "status": "running",
        "conversation_ready": conversation_ready,
        "memory_active": memory_status,
        "memory_sync": memory_sync,
        "reasoning": reasoning,
        "org_brain": {
            "service_ready": org_svc is not None,
            "enabled_default": bool(org_profile.get("enabled", False)),
            "org_id_default": str(org_profile.get("org_id") or ""),
        },
        "self_evolve": {
            "service_ready": self_evolve_svc is not None,
            "enabled_default": bool(self_evolve_profile.get("enabled", False)),
            "core_capability": "controlled_code_evolution",
        },
        "scheduler": scheduler_status,
        "workflow_recovery": workflow_recovery,
        "startup": dict(state.startup_report or {}),
    }


@router.get("/status/services")
async def get_services_status():
    gateway_server = get_gateway_server()
    health = gateway_server.get_services_health()
    failed = sorted([k for k, ok in health.items() if not bool(ok)])
    total = max(1, len(health))
    ok_count = total - len(failed)
    ratio = ok_count / total
    if ratio >= 0.99:
        overall = "healthy"
    elif ratio >= 0.5:
        overall = "degraded"
    else:
        overall = "unhealthy"
    recommendations = [
        {
            "component": name,
            "action": f"initialize {name} and verify runtime dependencies",
        }
        for name in failed
    ]
    return {
        "status": overall,
        "summary": {"total": total, "ok": ok_count, "failed": len(failed)},
        "services": health,
        "failed_services": failed,
        "recommendations": recommendations,
        "startup": dict(state.startup_report or {}),
    }


@router.get("/health/memory")
async def get_memory_health():
    gateway_server = get_gateway_server()
    memory_service = getattr(gateway_server, "memory_service", None)
    if memory_service is None:
        return {
            "status": "unavailable",
            "enabled": False,
            "configured_backend": None,
            "active_backend": None,
            "ready": False,
            "reason": "memory_service_not_initialized",
        }

    adapter = getattr(memory_service, "memory_adapter", None)
    configured_backend = (
        str(getattr(adapter, "store_backend", "") or "").strip().lower() if adapter else None
    )
    active_backend = None
    if adapter is not None:
        store = getattr(adapter, "store", None)
        if store is not None:
            active_backend = str(
                getattr(store, "backend_name", configured_backend) or configured_backend
            )
        elif getattr(adapter, "hot_layer", None) is not None:
            active_backend = "neo4j"

    enabled = bool(getattr(memory_service, "enabled", False))
    ready = bool(memory_service.is_enabled())
    sync = memory_service.get_sync_stats()
    status = "healthy" if ready else ("disabled" if not enabled else "degraded")
    reason = ""
    if not ready:
        if not enabled:
            reason = "memory_disabled_or_unavailable"
        elif configured_backend == "neo4j":
            reason = "neo4j_not_ready"
        else:
            reason = "backend_not_ready"

    return {
        "status": status,
        "enabled": enabled,
        "configured_backend": configured_backend,
        "active_backend": active_backend,
        "ready": ready,
        "sync": sync,
        "reason": reason,
    }


@router.get("/status/routes")
async def get_gateway_routes(request: Request):
    gateway_server = get_gateway_server()
    methods = sorted([str(k.value) for k in gateway_server._handlers.keys()])  # noqa: SLF001
    http_routes = []
    for route in request.app.routes:
        path = getattr(route, "path", "")
        if isinstance(path, str) and path.startswith("/api"):
            http_routes.append(path)
    http_routes = sorted(set(http_routes))
    return {
        "status": "success",
        "gateway_methods": methods,
        "http_routes": http_routes,
        "counts": {"gateway_methods": len(methods), "http_routes": len(http_routes)},
    }


@router.get("/status/tools")
async def get_tools_status():
    gateway_server = _ensure_tool_service()
    catalog = await gateway_server.tool_service.get_tool_catalog()
    by_type: dict[str, int] = {}
    for item in catalog:
        tool_type = str(item.get("tool_type", "unknown") or "unknown")
        by_type[tool_type] = by_type.get(tool_type, 0) + 1

    return {
        "status": "success",
        "total": len(catalog),
        "by_type": by_type,
        "tools": catalog,
    }


@router.get("/status/tools/official")
async def get_official_tools_status():
    gateway_server = _ensure_tool_service()
    registered = getattr(gateway_server.tool_service, "_registered_tools", {}) or {}
    items = []
    domains: dict[str, int] = {}
    for tool_id, tool in registered.items():
        if not bool(getattr(tool, "official", False)):
            continue
        domain = str(getattr(tool, "official_domain", "misc") or "misc")
        domains[domain] = domains.get(domain, 0) + 1
        items.append(
            {
                "tool_id": tool_id,
                "name": str(getattr(tool, "name", tool_id)),
                "description": str(getattr(tool, "description", "")),
                "domain": domain,
            }
        )
    items.sort(key=lambda x: (x["domain"], x["tool_id"]))
    return {
        "status": "success",
        "total": len(items),
        "by_domain": domains,
        "tools": items,
    }


