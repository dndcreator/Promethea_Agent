from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .spec import SideEffectLevel, ToolSource, ToolSpec


class ToolRegistry:
    """Unified registry for local and MCP tool specs."""

    def __init__(self) -> None:
        self._specs: Dict[str, ToolSpec] = {}

    def register_spec(self, spec: ToolSpec) -> None:
        self._specs[spec.full_name] = spec

    def unregister_spec(self, full_name: str) -> None:
        self._specs.pop(full_name, None)

    def register_local_tool(self, tool: Any) -> ToolSpec:
        tool_id = str(getattr(tool, "tool_id", getattr(tool, "name", "unknown.tool")))
        service_name = None
        tool_name = tool_id
        if "." in tool_id:
            service_name, tool_name = tool_id.split(".", 1)
        description = str(getattr(tool, "description", ""))
        source = getattr(tool, "tool_source", ToolSource.LOCAL)
        if not isinstance(source, ToolSource):
            source = ToolSource(str(source))
        spec = ToolSpec(
            tool_name=tool_name,
            service_name=service_name,
            description=description,
            input_schema=dict(getattr(tool, "input_schema", {}) or {}),
            output_schema=dict(getattr(tool, "output_schema", {}) or {}),
            side_effect_level=getattr(tool, "side_effect_level", None)
            or SideEffectLevel.PRIVILEGED_HOST_ACTION,
            timeout_ms=int(getattr(tool, "timeout_ms", 30000) or 30000),
            retry_policy=dict(getattr(tool, "retry_policy", {}) or {"max_retries": 0}),
            idempotency_hint=str(getattr(tool, "idempotency_hint", "unknown") or "unknown"),
            source=source,
            capability_type="extension" if source == ToolSource.EXTENSION else "local",
            metadata={
                "tool_id": tool_id,
                "declared_side_effect": bool(getattr(tool, "side_effect_level", None)),
                "side_effect_selector": dict(getattr(tool, "side_effect_selector", {}) or {}),
                "requires_capability": str(getattr(tool, "requires_capability", "") or ""),
                "requires_config": getattr(tool, "requires_config", None),
                "owner_user_id": str(getattr(tool, "owner_user_id", "") or ""),
                "manifest_path": str(getattr(tool, "manifest_path", "") or ""),
                "extension_id": str(getattr(tool, "extension_id", "") or ""),
                "extension_name": str(getattr(tool, "extension_name", "") or ""),
                "extension_version": str(getattr(tool, "extension_version", "") or ""),
            },
        )
        self.register_spec(spec)
        return spec

    def register_mcp_services(self, services: Dict[str, Any]) -> None:
        mcp_services = services.get("mcp_services", []) if isinstance(services, dict) else []
        for svc in mcp_services:
            service_name = str(svc.get("name") or "")
            if not service_name:
                continue
            service_desc = str(svc.get("description") or "")
            actions = svc.get("available_tools") or []
            if not actions:
                spec = ToolSpec(
                    tool_name=service_name,
                    service_name=service_name,
                    description=service_desc,
                    side_effect_level=SideEffectLevel.PRIVILEGED_HOST_ACTION,
                    source=ToolSource.MCP,
                    capability_type="mcp",
                )
                self.register_spec(spec)
                continue

            for action in actions:
                action_name = str(action.get("name") or service_name)
                action_desc = str(action.get("description") or service_desc)
                full_name = f"{service_name}.{action_name}"
                spec = ToolSpec(
                    tool_name=action_name,
                    service_name=service_name,
                    description=action_desc,
                    side_effect_level=(
                        action.get("side_effect_level")
                        or SideEffectLevel.PRIVILEGED_HOST_ACTION
                    ),
                    source=ToolSource.MCP,
                    capability_type="mcp",
                    input_schema=action.get("input_schema") or {},
                    metadata={
                        "declared_side_effect": bool(action.get("side_effect_level")),
                        "side_effect_selector": action.get("side_effect_selector") or {},
                        "requires_capability": str(action.get("requires_capability") or ""),
                        "requires_config": action.get("requires_config"),
                        "owner_user_id": action.get("owner_user_id"),
                    },
                )
                self.register_spec(spec)

    def replace_mcp_services(self, services: Dict[str, Any]) -> None:
        for full_name, spec in list(self._specs.items()):
            if spec.source == ToolSource.MCP:
                self._specs.pop(full_name, None)
        self.register_mcp_services(services)

    def normalize_call(self, *, tool_name: str, params: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Normalize model-produced tool calls to a registered canonical tool id.

        MCP manifests expose tools as ``<service>.<action>``. LLMs sometimes swap
        ``tool_name`` and ``service_name`` or omit one of them. This method keeps
        that tolerance registry-driven: only shapes that can be mapped to an
        already registered spec are corrected.
        """
        params = dict(params or {})
        raw_tool_name = str(tool_name or "").strip()
        service_name = str(params.get("service_name") or "").strip()
        actual_tool_name = str(params.get("tool_name") or params.get("command") or raw_tool_name).strip()
        agent_type = str(params.get("agentType") or "").lower()

        if agent_type == "agent":
            return raw_tool_name, params

        if raw_tool_name in self._specs and self._specs[raw_tool_name].source in {
            ToolSource.LOCAL,
            ToolSource.EXTENSION,
        }:
            return raw_tool_name, params

        candidates = []
        if raw_tool_name:
            candidates.append(raw_tool_name)
        if service_name and actual_tool_name:
            candidates.append(f"{service_name}.{actual_tool_name}")
        if raw_tool_name and service_name:
            candidates.append(f"{raw_tool_name}.{service_name}")
        if raw_tool_name and actual_tool_name and raw_tool_name != actual_tool_name:
            candidates.append(f"{raw_tool_name}.{actual_tool_name}")

        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            spec = self._specs.get(candidate)
            if spec is None:
                continue
            if spec.source in {ToolSource.LOCAL, ToolSource.EXTENSION}:
                return spec.full_name, params
            normalized = dict(params)
            normalized["agentType"] = "mcp"
            normalized["service_name"] = spec.service_name or spec.tool_name
            normalized["tool_name"] = spec.tool_name
            return spec.full_name, normalized

        # If a bare MCP action name is unique across services, map it safely.
        if raw_tool_name:
            matches = [
                spec
                for spec in self._specs.values()
                if spec.source == ToolSource.MCP and spec.tool_name == raw_tool_name
            ]
            if len(matches) == 1:
                spec = matches[0]
                normalized = dict(params)
                normalized["agentType"] = "mcp"
                normalized["service_name"] = spec.service_name or spec.tool_name
                normalized["tool_name"] = spec.tool_name
                return spec.full_name, normalized

        return raw_tool_name, params

    def resolve(self, *, tool_name: str, params: Dict[str, Any]) -> ToolSpec:
        # Prefer exact full name.
        if tool_name in self._specs:
            return self._specs[tool_name]

        agent_type = str(params.get("agentType") or "").lower()
        if agent_type == "agent":
            agent_name = str(params.get("agent_name") or tool_name or "agent")
            full_name = f"agent.{agent_name}"
            existing = self._specs.get(full_name)
            if existing:
                return existing
            spec = ToolSpec(
                tool_name=agent_name,
                service_name="agent",
                description="Agent handoff tool",
                source=ToolSource.AGENT,
                capability_type="agent",
                side_effect_level=SideEffectLevel.EXTERNAL_WRITE,
            )
            self.register_spec(spec)
            return spec

        service_name = str(params.get("service_name") or tool_name)
        actual_tool_name = str(params.get("tool_name") or params.get("command") or tool_name)
        full_name = f"{service_name}.{actual_tool_name}"
        existing = self._specs.get(full_name)
        if existing:
            return existing

        # Undeclared tools fail closed at the policy boundary. Risk must come
        # from a manifest or an explicit local ToolSpec, never name heuristics.
        spec = ToolSpec(
            tool_name=actual_tool_name,
            service_name=service_name,
            description="",
            source=ToolSource.MCP,
            capability_type="mcp",
            side_effect_level=SideEffectLevel.PRIVILEGED_HOST_ACTION,
            metadata={"inferred": True, "risk_metadata_missing": True},
        )
        self.register_spec(spec)
        return spec

    def resolve_for_call(self, *, tool_name: str, params: Dict[str, Any]) -> ToolSpec:
        """Resolve a spec and apply manifest-declared parameterized effects."""
        spec = self.resolve(tool_name=tool_name, params=params)
        selector = spec.metadata.get("side_effect_selector")
        if not isinstance(selector, dict):
            return spec
        parameter = str(selector.get("parameter") or "").strip()
        groups = selector.get("groups")
        if not parameter or not isinstance(groups, dict):
            return spec
        selected = str(params.get(parameter) or "").strip().lower()
        effect = selector.get("default")
        for level, values in groups.items():
            normalized = {str(value).strip().lower() for value in (values or [])}
            if selected in normalized:
                effect = level
                break
        if not effect:
            return spec
        return spec.model_copy(update={"side_effect_level": SideEffectLevel(str(effect))})

    def list_specs(self) -> List[ToolSpec]:
        return list(self._specs.values())
