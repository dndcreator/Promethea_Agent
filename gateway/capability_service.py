from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol
from uuid import uuid4

from loguru import logger

from agentkit.mcp.mcp_manager import MCPManager, get_mcp_manager
from agentkit.mcp.invocation_context import bind_invocation_context
from agentkit.mcp.tool_result import error_from_exception, normalize_tool_result
from agentkit.security.approval import approval_scope, matches_approved_call

from .events import EventEmitter
from .protocol import EventType
from .runtime_hooks import RuntimeHookManager, get_runtime_hook_manager
from .temporal import resolve_context_timezone_name
from .tools import SideEffectLevel, ToolPolicy, ToolPolicyDecision, ToolRegistry


@dataclass
class ToolInvocationContext:
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ToolPolicyViolationError(RuntimeError):
    def __init__(self, message: str, decision: Optional[ToolPolicyDecision] = None):
        super().__init__(message)
        self.decision = decision


class ToolCapabilityUnavailableError(RuntimeError):
    code = "CAPABILITY_UNAVAILABLE"
    category = "capability"
    retryable = True

    def __init__(self, capability: str, reason: str):
        self.capability = capability
        self.reason = reason
        super().__init__(f"Capability '{capability}' is unavailable: {reason}")


class Tool(Protocol):
    tool_id: str
    name: str
    description: str

    async def invoke(
        self,
        args: Dict[str, Any],
        ctx: Optional[ToolInvocationContext] = None,
    ) -> Any:  # pragma: no cover - protocol interface
        ...


class CapabilityService:
    """First-class execution boundary for tools, policies, and runtime capabilities."""

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        mcp_manager: Optional[MCPManager] = None,
        tool_registry: Optional[ToolRegistry] = None,
        tool_policy: Optional[ToolPolicy] = None,
        hook_manager: Optional[RuntimeHookManager] = None,
        capability_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        config_provider: Optional[Callable[[str], Dict[str, Any]]] = None,
        computer_runtime: Optional[Any] = None,
        workspace_service: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.mcp_manager = mcp_manager or get_mcp_manager()
        self._registered_tools: Dict[str, Tool] = {}
        self.tool_registry = tool_registry or ToolRegistry()
        self.tool_policy = tool_policy or ToolPolicy()
        self.hook_manager = hook_manager or get_runtime_hook_manager()
        self.capability_provider = capability_provider
        self.config_provider = config_provider
        self.computer_runtime = computer_runtime
        self.workspace_service = workspace_service
        self._discovered_tool_sources: Dict[str, str] = {}
        self._tool_discovery_initialized = False

    async def execute_computer_action(self, capability: str, action: str, params: Dict[str, Any]) -> Any:
        """Execute a computer capability in the trusted workspace bound to this invocation."""
        from computer.base import ComputerResult
        from computer.execution_context import current_workspace

        if self.computer_runtime is None:
            return ComputerResult(success=False, error="Computer runtime is not initialized")
        scope = current_workspace()
        if scope is None:
            return ComputerResult(success=False, error="Computer action requires a workspace scope")
        result = await self.computer_runtime.execute(
            scope,
            str(getattr(capability, "value", capability)),
            action,
            dict(params or {}),
        )
        if str(getattr(capability, "value", capability)) == "environment":
            for lifecycle in list(result.metadata.get("lifecycle_events") or []):
                await self._emit_event(
                    EventType.ENVIRONMENT_STATE_CHANGED,
                    {
                        "kind": "environment",
                        "user_id": scope.user_id,
                        "workspace_id": scope.workspace_id,
                        **dict(scope.execution or {}),
                        **dict(lifecycle or {}),
                    },
                )
        return result

    def get_computer_status(self) -> Dict[str, Any]:
        """Return the status exposed by the active computer capability provider."""
        if not callable(self.capability_provider):
            return {}
        status = self.capability_provider()
        return dict(status) if isinstance(status, dict) else {}

    async def _execute_managed_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        source: str = "managed_runtime",
        invocation_context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        trusted = dict(invocation_context or {})
        user_id = str(trusted.get("user_id") or "").strip()
        user_config = self.config_provider(user_id) if user_id and callable(self.config_provider) else None
        ctx = ToolInvocationContext(
            session_id=str(trusted.get("session_id") or "") or None,
            user_id=user_id or None,
            source=source,
            metadata=trusted,
        )
        return await self.call_tool(
            tool_name=tool_name,
            params=params,
            ctx=ctx,
            user_config=user_config if isinstance(user_config, dict) else None,
        )

    def set_capability_provider(self, provider: Optional[Callable[[], Dict[str, Any]]]) -> None:
        self.capability_provider = provider

    def register_tool(self, tool: Tool) -> None:
        if tool.tool_id in self._registered_tools:
            logger.warning(f"Tool already registered: {tool.tool_id}, will overwrite")
        self._registered_tools[tool.tool_id] = tool
        self.tool_registry.register_local_tool(tool)
        logger.info(f"Registered local tool: {tool.tool_id}")

    def reload_discovered_tools(
        self,
        scan_dirs: Optional[List[str]] = None,
        *,
        reload_modules: bool = True,
    ) -> List[str]:
        """Atomically rescan manifest-backed tools and replace the affected snapshot."""
        from .tools.discovery import discover_manifest_tools

        project_root = Path(__file__).resolve().parents[1]
        official_root = (project_root / "agentkit" / "tools").resolve()
        roots = [Path(item).resolve() for item in (scan_dirs or [
            str(official_root),
            str(project_root / "extensions" / "community"),
        ])]
        staged = discover_manifest_tools(
            roots,
            official_root=official_root,
            reload_modules=reload_modules,
        )

        def _under_selected_root(source: str) -> bool:
            try:
                path = Path(source).resolve()
                return any(path.is_relative_to(root) for root in roots)
            except (OSError, ValueError):
                return False

        stale_ids = [
            tool_id
            for tool_id, source in self._discovered_tool_sources.items()
            if _under_selected_root(source)
        ]
        stale_set = set(stale_ids)
        collisions = [
            item.tool.tool_id
            for item in staged
            if item.tool.tool_id in self._registered_tools and item.tool.tool_id not in stale_set
        ]
        if collisions:
            raise ValueError(
                "manifest tool ids collide with existing runtime tools: "
                + ", ".join(sorted(collisions))
            )
        for tool_id in stale_ids:
            self.unregister_tool(tool_id)
            self._discovered_tool_sources.pop(tool_id, None)

        configured_services = set()
        for item in staged:
            tool = item.tool
            service = getattr(getattr(tool, "_method", None), "__self__", None)
            service_identity = id(service)
            if service is not None and service_identity not in configured_services:
                configured_services.add(service_identity)
                configure = getattr(service, "configure_tool_runtime", None)
                if callable(configure):
                    configure(
                        executor=self._execute_managed_tool,
                        confirmation_resolver=self.requires_confirmation,
                    )
                configure_reloader = getattr(service, "configure_extension_reloader", None)
                if callable(configure_reloader):
                    configure_reloader(self.reload_discovered_tools)
            self.register_tool(tool)
            self._discovered_tool_sources[tool.tool_id] = str(item.manifest_path.resolve())

        self._tool_discovery_initialized = True
        logger.info(
            "Tool discovery refreshed {} tools from {} roots",
            len(staged),
            len(roots),
        )
        return [item.tool.tool_id for item in staged]

    def ensure_discovered_tools(self) -> List[str]:
        if self._tool_discovery_initialized:
            return sorted(self._discovered_tool_sources)
        try:
            return self.reload_discovered_tools(reload_modules=False)
        except Exception as exc:
            project_root = Path(__file__).resolve().parents[1]
            logger.error("Tool discovery encountered an invalid manifest during startup: {}", exc)
            return self.reload_discovered_tools(
                [str(project_root / "agentkit" / "tools")],
                reload_modules=False,
            )

    def unregister_tool(self, tool_id: str) -> None:
        if tool_id in self._registered_tools:
            del self._registered_tools[tool_id]
            self.tool_registry.unregister_spec(tool_id)
            logger.info(f"Unregistered local tool: {tool_id}")

    def requires_confirmation(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        run_context: Optional[Any] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Use the execution registry and policy as the confirmation authority."""
        self._sync_registry_from_mcp()
        canonical_name, canonical_params = self.tool_registry.normalize_call(
            tool_name=tool_name,
            params=params,
        )
        spec = self.tool_registry.resolve_for_call(tool_name=canonical_name, params=canonical_params)
        decision = self.tool_policy.evaluate(
            spec=spec,
            run_context=run_context,
            user_config=user_config,
        )
        return bool(decision.requires_confirmation)

    def _sync_registry_from_mcp(self) -> None:
        try:
            services_filtered = self.mcp_manager.get_available_services_filtered()
            self.tool_registry.replace_mcp_services(services_filtered)
        except Exception as e:
            logger.debug(f"Tool registry MCP sync failed: {e}")

    async def list_tools(self) -> Dict[str, Any]:
        tools: List[Dict[str, Any]] = []
        self._sync_registry_from_mcp()

        try:
            services_filtered = self.mcp_manager.get_available_services_filtered()
            mcp_services = services_filtered.get("mcp_services", [])

            for svc in mcp_services:
                tools.append(
                    {
                        "service": svc.get("name"),
                        "name": svc.get("label", svc.get("name")),
                        "description": svc.get("description", ""),
                        "actions": svc.get("available_tools", []),
                        "type": "mcp",
                    }
                )

        except Exception as e:
            logger.error(f"Failed to list MCP/agent tools: {e}")

        for tool_id, tool in self._registered_tools.items():
            spec = self.tool_registry.resolve(tool_name=tool_id, params={})
            tools.append(
                {
                    "service": tool_id,
                    "name": getattr(tool, "name", tool_id),
                    "description": getattr(tool, "description", ""),
                    "actions": [],
                    "type": str(spec.source.value),
                }
            )

        return {"tools": tools, "total": len(tools)}

    def _capability_readiness(
        self,
        capability: str,
        *,
        statuses: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str, Dict[str, Any]]:
        if not capability:
            return True, "", {}
        provider = self.capability_provider
        if not callable(provider):
            return False, "capability_status_unavailable", {}
        try:
            statuses = statuses if isinstance(statuses, dict) else (provider() or {})
            key = capability.split(".", 1)[-1]
            row = statuses.get(capability) or statuses.get(key)
            if not isinstance(row, dict):
                return False, "capability_not_reported", {}
            ready = bool(row.get("ready", row.get("initialized", False)))
            reason = str(row.get("reason") or ("ready" if ready else "not_initialized"))
            public_details = {
                key: value
                for key, value in row.items()
                if key in {"available_locations"}
            }
            return ready, reason, public_details
        except Exception as e:
            logger.debug(f"Capability readiness probe failed [{capability}]: {e}")
            return False, "capability_probe_failed", {}

    def _dependency_readiness(
        self,
        *,
        tool_type: str,
        service_name: str,
        tool_name: str,
        health_by_service: Dict[str, Dict[str, Any]],
        capability_statuses: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str, str, Dict[str, Any]]:
        ready = True
        reason = ""
        if str(tool_type).lower() == "mcp":
            row = health_by_service.get(str(service_name))
            if row:
                status = str(row.get("status") or "").strip().lower()
                visibility = str(row.get("user_visibility") or "visible").strip().lower()
                ready = status in {"online", "healthy", "ready", "ok"} and visibility == "visible"
                if not ready:
                    reason = f"mcp_{status or 'offline'}"
        spec = self.tool_registry.resolve(
            tool_name=f"{service_name}.{tool_name}",
            params={"agentType": tool_type, "service_name": service_name, "tool_name": tool_name},
        )
        required = str(spec.metadata.get("requires_capability") or "").strip()
        capability_details: Dict[str, Any] = {}
        if ready and required:
            ready, capability_reason, capability_details = self._capability_readiness(
                required,
                statuses=capability_statuses,
            )
            if not ready:
                reason = f"{required}:{capability_reason}"
        return ready, reason, required, capability_details

    async def get_tool_catalog(
        self,
        *,
        run_context: Optional[Any] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        refresh = getattr(self.mcp_manager, "refresh_registered_tools", None)
        if callable(refresh):
            try:
                await refresh()
            except Exception as e:
                logger.debug(f"External MCP catalog refresh failed: {e}")
        raw = await self.list_tools()
        health_by_service: Dict[str, Dict[str, Any]] = {}
        user_id = str(getattr(run_context, "user_id", "") or "").strip() if run_context is not None else ""
        try:
            if self.mcp_manager and hasattr(self.mcp_manager, "list_service_health"):
                rows = self.mcp_manager.list_service_health(user_id=user_id or None) or []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    service_name = str(row.get("service_name") or row.get("id") or "").strip()
                    if service_name:
                        health_by_service[service_name] = row
        except Exception as e:
            logger.debug(f"Tool catalog health probe skipped: {e}")
        capability_statuses = self.get_computer_status()

        catalog: List[Dict[str, Any]] = []
        for service in raw.get("tools", []):
            service_name = service.get("service") or service.get("name")
            service_desc = service.get("description", "")
            tool_type = service.get("type", "unknown")
            actions = service.get("actions") or []
            if not actions:
                tool_name = service_name
                params = {"agentType": tool_type, "service_name": service_name, "tool_name": tool_name}
                spec = self.tool_registry.resolve(tool_name=str(tool_name), params=params)
                decision = None
                policy_allowed = True
                policy_reason = "allowed_by_default"
                if run_context is not None or user_config:
                    decision = self.tool_policy.evaluate(
                        spec=spec,
                        run_context=run_context,
                        user_config=user_config,
                    )
                    policy_allowed = bool(decision.allowed)
                    policy_reason = str(decision.reason or "")
                config_ready, config_reason = self._required_config_ready(
                    spec.metadata.get("requires_config"), user_config
                )
                dependency_ready, dependency_reason, required_capability, capability_details = self._dependency_readiness(
                    tool_type=str(tool_type),
                    service_name=str(service_name),
                    tool_name=str(tool_name),
                    health_by_service=health_by_service,
                    capability_statuses=capability_statuses,
                )
                owner_user_id = str(spec.metadata.get("owner_user_id") or "").strip()
                owner_ready = not owner_user_id or bool(user_id and owner_user_id == user_id)
                if owner_user_id and not owner_ready:
                    continue
                callable_now = bool(policy_allowed and dependency_ready and config_ready and owner_ready)
                callable_reason = "callable" if callable_now else (
                    "owner_mismatch" if not owner_ready else (config_reason or dependency_reason or policy_reason or "not_callable")
                )
                requires_confirmation = spec.side_effect_level in {
                    SideEffectLevel.EXTERNAL_WRITE,
                    SideEffectLevel.PRIVILEGED_HOST_ACTION,
                }
                catalog.append(
                    {
                        "tool_type": tool_type,
                        "service_name": service_name,
                        "tool_name": tool_name,
                        "description": service_desc,
                        "callable_now": callable_now,
                        "callable_reason": callable_reason,
                        "policy_allowed": policy_allowed,
                        "dependency_ready": dependency_ready,
                        "config_ready": config_ready,
                        "owner_ready": owner_ready,
                        "required_capability": required_capability or None,
                        "capability_details": capability_details,
                        "requires_confirmation": requires_confirmation,
                    }
                )
                continue
            for action in actions:
                tool_name = action.get("name") or service_name
                params = {"agentType": tool_type, "service_name": service_name, "tool_name": tool_name}
                spec = self.tool_registry.resolve(tool_name=str(tool_name), params=params)
                decision = None
                policy_allowed = True
                policy_reason = "allowed_by_default"
                if run_context is not None or user_config:
                    decision = self.tool_policy.evaluate(
                        spec=spec,
                        run_context=run_context,
                        user_config=user_config,
                    )
                    policy_allowed = bool(decision.allowed)
                    policy_reason = str(decision.reason or "")
                config_ready, config_reason = self._required_config_ready(
                    spec.metadata.get("requires_config"), user_config
                )
                dependency_ready, dependency_reason, required_capability, capability_details = self._dependency_readiness(
                    tool_type=str(tool_type),
                    service_name=str(service_name),
                    tool_name=str(tool_name),
                    health_by_service=health_by_service,
                    capability_statuses=capability_statuses,
                )
                owner_user_id = str(spec.metadata.get("owner_user_id") or "").strip()
                owner_ready = not owner_user_id or bool(user_id and owner_user_id == user_id)
                if owner_user_id and not owner_ready:
                    continue
                callable_now = bool(policy_allowed and dependency_ready and config_ready and owner_ready)
                callable_reason = "callable" if callable_now else (
                    "owner_mismatch" if not owner_ready else (config_reason or dependency_reason or policy_reason or "not_callable")
                )
                requires_confirmation = spec.side_effect_level in {
                    SideEffectLevel.EXTERNAL_WRITE,
                    SideEffectLevel.PRIVILEGED_HOST_ACTION,
                }
                catalog.append(
                    {
                        "tool_type": tool_type,
                        "service_name": service_name,
                        "tool_name": tool_name,
                        "description": action.get("description") or service_desc,
                        "callable_now": callable_now,
                        "callable_reason": callable_reason,
                        "policy_allowed": policy_allowed,
                        "dependency_ready": dependency_ready,
                        "config_ready": config_ready,
                        "owner_ready": owner_ready,
                        "required_capability": required_capability or None,
                        "capability_details": capability_details,
                        "requires_confirmation": requires_confirmation,
                    }
                )
        return catalog

    @staticmethod
    def _extract_run_context_fields(run_context: Optional[Any]) -> Dict[str, Any]:
        if run_context is None:
            return {}
        trace_id = getattr(run_context, "trace_id", None)
        request_id = getattr(run_context, "request_id", None)
        task_id = getattr(run_context, "task_id", None)
        run_id = getattr(run_context, "run_id", None)
        session_value = getattr(run_context, "session_id", None)
        user_value = getattr(run_context, "user_id", None)
        tenant_id = getattr(run_context, "tenant_id", None)
        environment = getattr(run_context, "environment", None)
        workspace_handle = getattr(run_context, "workspace_handle", None)
        workspace_id = (
            workspace_handle.get("workspace_id")
            if isinstance(workspace_handle, dict)
            else getattr(workspace_handle, "workspace_id", None)
        )
        if session_value is None:
            session_state = getattr(run_context, "session_state", None)
            session_value = getattr(session_state, "session_id", None) if session_state is not None else None
            if user_value is None:
                user_value = getattr(session_state, "user_id", None) if session_state is not None else None
            if trace_id is None:
                trace_id = getattr(session_state, "trace_id", None) if session_state is not None else None
            if tenant_id is None:
                tenant_id = getattr(session_state, "tenant_id", None) if session_state is not None else None
            if environment is None:
                environment = getattr(session_state, "environment", None) if session_state is not None else None
        fields: Dict[str, Any] = {}
        if trace_id:
            fields["trace_id"] = str(trace_id)
        if request_id:
            fields["request_id"] = str(request_id)
        if task_id:
            fields["task_id"] = str(task_id)
        if run_id:
            fields["run_id"] = str(run_id)
        if session_value:
            fields["session_id"] = str(session_value)
        if user_value:
            fields["user_id"] = str(user_value)
        if tenant_id:
            fields["tenant_id"] = str(tenant_id)
        if environment:
            fields["environment"] = str(environment)
        if workspace_id:
            fields["workspace_id"] = str(workspace_id)
        input_payload = getattr(run_context, "input_payload", None)
        metadata = input_payload.get("metadata") if isinstance(input_payload, dict) else None
        if isinstance(metadata, dict) and metadata.get("timezone"):
            fields["timezone"] = str(metadata["timezone"])
        return fields

    def _build_context_fields(
        self,
        *,
        ctx: Optional[ToolInvocationContext],
        run_context: Optional[Any],
    ) -> Dict[str, Any]:
        fields = self._extract_run_context_fields(run_context)
        if ctx:
            if ctx.session_id:
                fields["session_id"] = str(ctx.session_id)
            if ctx.user_id:
                fields["user_id"] = str(ctx.user_id)
            if ctx.source:
                fields["source"] = ctx.source
            metadata = ctx.metadata or {}
            if isinstance(metadata, dict):
                trace_id = metadata.get("trace_id")
                if trace_id and "trace_id" not in fields:
                    fields["trace_id"] = str(trace_id)
                request_meta = metadata.get("request_id")
                if request_meta and "request_id" not in fields:
                    fields["request_id"] = str(request_meta)
                for key in (
                    "tree_id",
                    "node_id",
                    "tool_call_id",
                    "task_id",
                    "run_id",
                    "workspace_id",
                    "timezone",
                ):
                    value = metadata.get(key)
                    if value and key not in fields:
                        fields[key] = str(value)
        return fields

    async def _assert_tool_namespace(
        self,
        *,
        run_context: Optional[Any],
        context_fields: Dict[str, Any],
        request_id: Optional[str],
        connection_id: Optional[str],
    ) -> None:
        if run_context is None:
            return
        context_user_id = str(context_fields.get("user_id") or "").strip()
        run_user_id = str(getattr(run_context, "user_id", "") or "").strip()
        if context_user_id and run_user_id and context_user_id != run_user_id:
            payload = {
                "request_id": request_id,
                "connection_id": connection_id,
                **context_fields,
                "namespace": "tool",
                "owner_user_id": run_user_id,
                "requester_user_id": context_user_id,
                "reason": "cross_user_tool_access",
                "outcome": "blocked",
            }
            await self._emit_event(EventType.SECURITY_BOUNDARY_VIOLATION, payload)
            await self._emit_event(EventType.TOOL_CALL_ERROR, {**payload, "error": "forbidden tool access"})
            raise ToolPolicyViolationError("forbidden tool access")

    async def _authorize_tool_call(
        self,
        *,
        tool_name: str,
        params: Dict[str, Any],
        run_context: Optional[Any],
        context_fields: Dict[str, Any],
        request_id: Optional[str],
        connection_id: Optional[str],
        user_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        await self._assert_tool_namespace(
            run_context=run_context,
            context_fields=context_fields,
            request_id=request_id,
            connection_id=connection_id,
        )
        self._sync_registry_from_mcp()
        spec = self.tool_registry.resolve_for_call(tool_name=tool_name, params=params)

        owner_user_id = str(spec.metadata.get("owner_user_id") or "").strip()
        requester_user_id = str(context_fields.get("user_id") or "").strip()
        if owner_user_id and requester_user_id != owner_user_id:
            raise ToolPolicyViolationError("tool is private to another user")

        config_ready, config_reason = self._required_config_ready(
            spec.metadata.get("requires_config"), user_config
        )
        if not config_ready:
            await self._emit_event(
                EventType.TOOL_CALL_ERROR,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    **context_fields,
                    "tool_type": str(spec.source.value),
                    "tool_name": spec.full_name,
                    "error": config_reason,
                    "status": "blocked",
                    "ok": False,
                },
            )
            raise ToolPolicyViolationError(config_reason)

        decision = self.tool_policy.evaluate(spec=spec, run_context=run_context, user_config=user_config)
        if not decision.allowed:
            payload = {
                "request_id": request_id,
                "connection_id": connection_id,
                **context_fields,
                "tool_type": str(spec.source.value),
                "tool_name": spec.full_name,
                "error": decision.reason,
                "policy": decision.effective or {},
            }
            await self._emit_event(EventType.TOOL_CALL_ERROR, payload)
            raise ToolPolicyViolationError(decision.reason, decision=decision)

        return {"spec": spec, "decision": decision}

    @staticmethod
    def _required_config_ready(requirement: Any, user_config: Optional[Dict[str, Any]]) -> tuple[bool, str]:
        if not requirement:
            return True, ""
        if isinstance(requirement, str):
            path = requirement
            expected: Any = True
        elif isinstance(requirement, dict):
            path = str(requirement.get("path") or "").strip()
            expected = requirement.get("equals", True)
        else:
            return False, "invalid manifest requiresConfig declaration"
        if not path:
            return False, "manifest requiresConfig path is empty"
        current: Any = user_config if isinstance(user_config, dict) else {}
        for segment in path.split("."):
            if not isinstance(current, dict) or segment not in current:
                return False, f"required config is not enabled: {path}"
            current = current[segment]
        if current != expected:
            return False, f"required config is not enabled: {path}"
        return True, ""

    async def _assert_capability_ready(
        self,
        *,
        tool_name: str,
        params: Dict[str, Any],
        context_fields: Dict[str, Any],
        request_id: Optional[str],
        connection_id: Optional[str],
    ) -> None:
        # Standalone callers historically have no host capability provider.
        # The real Gateway always injects one and therefore fails closed.
        if not callable(self.capability_provider):
            return
        spec = self.tool_registry.resolve_for_call(tool_name=tool_name, params=params)
        service_name = str(spec.service_name or params.get("service_name") or tool_name)
        actual_tool_name = str(spec.tool_name)
        capability = str(spec.metadata.get("requires_capability") or "").strip()
        if not capability:
            return
        ready, reason, _ = self._capability_readiness(capability)
        if ready:
            return
        error = ToolCapabilityUnavailableError(capability, reason)
        await self._emit_event(
            EventType.TOOL_CALL_ERROR,
            {
                "request_id": request_id,
                "connection_id": connection_id,
                **context_fields,
                "tool_type": str(spec.source.value),
                "service_name": service_name,
                "tool_name": actual_tool_name,
                "status": "failed",
                "ok": False,
                "error": str(error),
                "error_detail": {
                    "code": error.code,
                    "message": str(error),
                    "category": error.category,
                    "retryable": error.retryable,
                    "dependency": capability,
                },
            },
        )
        raise error

    async def _emit_tool_outcome(
        self,
        *,
        tool_name: str,
        result: Any,
        payload: Dict[str, Any],
        result_summary: Any = None,
        result_metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        normalized = normalize_tool_result(tool_name, result)
        event_payload = {**payload, **normalized.event_fields()}
        if result_summary is not None:
            event_payload["result_summary"] = result_summary
        if result_metadata:
            event_payload["result_metadata"] = dict(result_metadata)
        if normalized.ok:
            await self._emit_event(EventType.TOOL_CALL_RESULT, event_payload)
        else:
            event_payload["error"] = normalized.error.message if normalized.error else "tool call failed"
            await self._emit_event(EventType.TOOL_CALL_ERROR, event_payload)
        return normalized

    @staticmethod
    def _project_local_result(tool: Tool, result: Any) -> tuple[Any, Dict[str, Any]]:
        summary = None
        metadata: Dict[str, Any] = {}
        summary_builder = getattr(tool, "result_summary", None)
        metadata_builder = getattr(tool, "result_metadata", None)
        try:
            if callable(summary_builder):
                summary = summary_builder(result)
            if callable(metadata_builder):
                projected = metadata_builder(result)
                if isinstance(projected, dict):
                    metadata = projected
        except Exception as exc:
            logger.warning(f"Tool result projection failed [{tool.tool_id}]: {exc}")
        return summary, metadata

    def _workspace_scope(self, params: Dict[str, Any], context_fields: Dict[str, Any]):
        service = getattr(self, "workspace_service", None)
        user_id = str(context_fields.get("user_id") or "").strip()
        if service is None or not user_id:
            return nullcontext()
        requested_user = str(params.get("user_id") or "").strip()
        if requested_user and requested_user != user_id:
            raise PermissionError("tool user_id differs from invocation context")
        from computer.execution_context import bind_workspace

        handle = service.resolve_workspace_handle(
            user_id=user_id,
            workspace_id=str(
                params.get("workspace_id")
                or context_fields.get("workspace_id")
                or context_fields.get("session_id")
                or "default"
            ),
        )
        return bind_workspace(handle, context_fields)

    async def call_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        ctx: Optional[ToolInvocationContext] = None,
        request_id: Optional[str] = None,
        connection_id: Optional[str] = None,
        run_context: Optional[Any] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Any:
        approved = matches_approved_call(tool_name, params)
        self._sync_registry_from_mcp()
        tool_name, params = self.tool_registry.normalize_call(tool_name=tool_name, params=params)
        context_fields = self._build_context_fields(ctx=ctx, run_context=run_context)
        context_fields["timezone"] = resolve_context_timezone_name(
            user_config,
            str(context_fields.get("timezone") or ""),
        )
        context_fields.setdefault("tool_call_id", f"tool_exec_{uuid4().hex}")
        await self._assert_capability_ready(
            tool_name=tool_name,
            params=params,
            context_fields=context_fields,
            request_id=request_id,
            connection_id=connection_id,
        )
        auth = await self._authorize_tool_call(
            tool_name=tool_name,
            params=params,
            run_context=run_context,
            context_fields=context_fields,
            request_id=request_id,
            connection_id=connection_id,
            user_config=user_config,
        )
        spec = auth["spec"]
        decision = auth["decision"]
        hook_payload_base = {
            "tool_name": str(tool_name),
            "params": dict(params or {}),
            "request_id": request_id,
            "connection_id": connection_id,
            "context": dict(context_fields or {}),
            "spec": spec.model_dump(mode="json"),
            "policy": (decision.effective if decision else {}),
        }
        await self._run_hook("before_tool_call", hook_payload_base)

        local_tool = self._registered_tools.get(tool_name)
        if local_tool is not None:
            await self._emit_event(
                EventType.TOOL_CALL_START,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    **context_fields,
                    "tool_type": "local",
                    "tool_id": tool_name,
                    "args": params,
                    "tool_spec": spec.model_dump(mode="json"),
                    "policy": (decision.effective if decision else {}),
                },
            )
            try:
                with self._workspace_scope(params, context_fields), bind_invocation_context(context_fields), approval_scope(tool_name, params, confirmed=approved):
                    result = await local_tool.invoke(params, ctx)
                result_summary, result_metadata = self._project_local_result(local_tool, result)
                normalized = await self._emit_tool_outcome(
                    tool_name=tool_name,
                    result=result,
                    payload={
                        "request_id": request_id,
                        "connection_id": connection_id,
                        **context_fields,
                        "tool_type": "local",
                        "tool_id": tool_name,
                    },
                    result_summary=result_summary,
                    result_metadata=result_metadata,
                )
                await self._run_hook(
                    "after_tool_call" if normalized.ok else "on_tool_error",
                    {
                        **hook_payload_base,
                        "result": result,
                        "error": normalized.error.message if normalized.error else None,
                        "tool_type": "local",
                    },
                )
                return result
            except Exception as e:
                logger.error(f"Local tool invocation failed [{tool_name}]: {e}")
                error_detail = error_from_exception(e)
                await self._emit_event(
                    EventType.TOOL_CALL_ERROR,
                    {
                        "request_id": request_id,
                        "connection_id": connection_id,
                        **context_fields,
                        "tool_type": "local",
                        "tool_id": tool_name,
                        "error": str(e),
                        "ok": False,
                        "status": "failed",
                        "error_detail": error_detail.as_dict(),
                    },
                )
                await self._run_hook(
                    "on_tool_error",
                    {
                        **hook_payload_base,
                        "error": str(e),
                        "tool_type": "local",
                    },
                )
                raise

        agent_type = str(params.get("agentType") or "").lower()
        if agent_type == "agent":
            agent_name = params.get("agent_name")
            prompt = params.get("prompt")
            if not agent_name or not prompt:
                raise ValueError("agent tool call requires agent_name and prompt")
            await self._emit_event(
                EventType.TOOL_CALL_START,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    **context_fields,
                    "tool_type": "agent",
                    "agent_name": agent_name,
                    "tool_spec": spec.model_dump(mode="json"),
                    "policy": (decision.effective if decision else {}),
                },
            )
            try:
                from agentkit.mcp.agent_manager import get_agent_manager

                agent_manager = get_agent_manager()
                agent_result = await agent_manager.call_agent(
                    str(agent_name),
                    str(prompt),
                    getattr(ctx, "session_id", None) if ctx else None,
                )
                if not isinstance(agent_result, dict) or agent_result.get("status") != "success":
                    error = (
                        agent_result.get("error")
                        if isinstance(agent_result, dict)
                        else "invalid agent response"
                    )
                    raise RuntimeError(error or "agent call failed")
                result = agent_result.get("result", "")
                normalized = await self._emit_tool_outcome(
                    tool_name=f"agent.{agent_name}",
                    result=result,
                    payload={
                        "request_id": request_id,
                        "connection_id": connection_id,
                        **context_fields,
                        "tool_type": "agent",
                        "agent_name": agent_name,
                    },
                )
                await self._run_hook(
                    "after_tool_call" if normalized.ok else "on_tool_error",
                    {
                        **hook_payload_base,
                        "result": result,
                        "error": normalized.error.message if normalized.error else None,
                        "tool_type": "agent",
                    },
                )
                return result
            except Exception as e:
                error_detail = error_from_exception(e)
                await self._emit_event(
                    EventType.TOOL_CALL_ERROR,
                    {
                        "request_id": request_id,
                        "connection_id": connection_id,
                        **context_fields,
                        "tool_type": "agent",
                        "agent_name": agent_name,
                        "error": str(e),
                        "ok": False,
                        "status": "failed",
                        "error_detail": error_detail.as_dict(),
                    },
                )
                await self._run_hook(
                    "on_tool_error",
                    {
                        **hook_payload_base,
                        "error": str(e),
                        "tool_type": "agent",
                    },
                )
                raise

        service_name = params.get("service_name") or tool_name
        actual_tool_name = params.get("tool_name") or params.get("command") or tool_name
        args = {
            k: v
            for k, v in params.items()
            if k not in {"service_name", "tool_name", "agentType"}
        }

        await self._emit_event(
            EventType.TOOL_CALL_START,
            {
                "request_id": request_id,
                "connection_id": connection_id,
                **context_fields,
                "tool_type": "mcp",
                "service_name": service_name,
                "tool_name": actual_tool_name,
                "args": args,
                "tool_spec": spec.model_dump(mode="json"),
                "policy": (decision.effective if decision else {}),
            },
        )

        try:
            with self._workspace_scope(params, context_fields), bind_invocation_context(context_fields), approval_scope(tool_name, params, confirmed=approved):
                result = await self.mcp_manager.call_service_tool(
                    service_name=service_name,
                    tool_name=actual_tool_name,
                    args=args,
                )
            if result is None:
                raise RuntimeError(
                    f"MCP tool returned no result: {service_name}.{actual_tool_name}"
                )
            normalized = await self._emit_tool_outcome(
                tool_name=f"{service_name}.{actual_tool_name}",
                result=result,
                payload={
                    "request_id": request_id,
                    "connection_id": connection_id,
                    **context_fields,
                    "tool_type": "mcp",
                    "service_name": service_name,
                    "tool_name": actual_tool_name,
                },
            )
            await self._run_hook(
                "after_tool_call" if normalized.ok else "on_tool_error",
                {
                    **hook_payload_base,
                    "result": result,
                    "error": normalized.error.message if normalized.error else None,
                    "tool_type": "mcp",
                    "service_name": service_name,
                    "actual_tool_name": actual_tool_name,
                },
            )
            return result
        except Exception as e:
            logger.error(f"MCP tool invocation failed [{service_name}.{actual_tool_name}]: {e}")
            error_detail = error_from_exception(e)
            await self._emit_event(
                EventType.TOOL_CALL_ERROR,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    **context_fields,
                    "tool_type": "mcp",
                    "service_name": service_name,
                    "tool_name": actual_tool_name,
                    "error": str(e),
                    "ok": False,
                    "status": "failed",
                    "error_detail": error_detail.as_dict(),
                },
            )
            await self._run_hook(
                "on_tool_error",
                {
                    **hook_payload_base,
                    "error": str(e),
                    "tool_type": "mcp",
                    "service_name": service_name,
                    "actual_tool_name": actual_tool_name,
                },
            )
            raise

    async def _run_hook(self, hook_name: str, payload: Dict[str, Any]) -> None:
        manager = self.hook_manager
        if manager is None:
            return
        fn = getattr(manager, hook_name, None)
        if not callable(fn):
            return
        try:
            maybe = fn(dict(payload or {}))
            if hasattr(maybe, "__await__"):
                await maybe
        except Exception as e:
            logger.debug(f"CapabilityService hook '{hook_name}' failed (ignored): {e}")

    async def _emit_event(self, event: EventType, payload: Dict[str, Any]) -> None:
        if not self.event_emitter:
            return
        mirror_map = {
            EventType.TOOL_CALL_START: EventType.TOOL_EXECUTION_STARTED,
            EventType.TOOL_CALL_RESULT: EventType.TOOL_EXECUTION_FINISHED,
            EventType.TOOL_CALL_ERROR: EventType.TOOL_EXECUTION_FAILED,
        }
        try:
            await self.event_emitter.emit(event, payload)
            canonical_event = mirror_map.get(event)
            if canonical_event is not None:
                await self.event_emitter.emit(canonical_event, payload)
        except Exception as e:
            logger.error(f"Failed to emit tool event {event}: {e}")


