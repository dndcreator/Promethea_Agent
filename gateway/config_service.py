from __future__ import annotations

"""
Configuration system service layer.

Goals:
- Extract all "configuration" capabilities in the Gateway into a standalone ConfigService.
- Manage default configuration, per-user configuration, and environment variables (secrets).
- Provide creation, update, query, reset, and hot-reload functionality for configuration.
- Publish configuration change events via the event bus so that other services can react automatically.
- Serve as the central entrypoint for model switching and other config-related features.
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional
from loguru import logger

from .events import EventEmitter
from .protocol import EventType
from config import PrometheaConfig, load_config
from gateway.http.user_manager import user_manager
from agentkit.security.sandbox import reload_sandbox_policy
from .config_migrations import (
    CURRENT_CONFIG_VERSION,
    collect_deprecation_warnings,
    migrate_config,
)


class ConfigService:
    """
    Configuration service (single entrypoint exposed to the Gateway).

    - Manages three layers of configuration: default, user, and environment variables.
    - Provides creation, update, query, reset, and hot-reload APIs.
    - Emits CONFIG_* events on the EventEmitter so other services can react to changes.
    - Acts as the central hub for model switching and other config-related operations.
    """

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
    ) -> None:
        self.event_emitter = event_emitter

        self._default_config: Optional[PrometheaConfig] = None
        self._user_config_cache: Dict[str, Dict[str, Any]] = {}
        self._deprecation_warnings: Dict[str, list[str]] = {}

        self._load_default_config()

        logger.info("ConfigService: Initialized")
    
    def _load_default_config(self) -> None:
        """Load the default (system-level) configuration."""
        try:
            self._default_config = load_config()
            logger.info("ConfigService: Default config loaded")
        except Exception as e:
            logger.error(f"ConfigService: Failed to load default config: {e}")
            # Fallback: use an empty config to keep the service usable
            self._default_config = PrometheaConfig()
    
    def _migrate_payload(
        self,
        payload: Dict[str, Any],
        *,
        warning_key: str,
    ) -> Dict[str, Any]:
        migrated, report = migrate_config(payload if isinstance(payload, dict) else {})
        warnings = list(report.get("warnings") or [])
        warnings.extend(collect_deprecation_warnings(migrated))
        if warnings:
            self._deprecation_warnings[warning_key] = sorted(set(str(w) for w in warnings if str(w).strip()))
        elif warning_key in self._deprecation_warnings:
            self._deprecation_warnings.pop(warning_key, None)
        return migrated

    @staticmethod
    def _scope_slice(payload: Dict[str, Any], scope: Optional[str]) -> Dict[str, Any]:
        if not scope:
            return payload
        cur: Any = payload
        for part in [p for p in str(scope).split(".") if p]:
            if not isinstance(cur, dict):
                return {}
            cur = cur.get(part)
            if cur is None:
                return {}
        return cur if isinstance(cur, dict) else {"value": cur}

    def get_deprecation_warnings(self, user_id: Optional[str] = None) -> list[str]:
        key = user_id if user_id else "default"
        return list(self._deprecation_warnings.get(key, []))

    # ===== Configuration query APIs =====
    
    def get_default_config(self) -> PrometheaConfig:
        """
        Get the default (system-level) configuration.
        
        Returns:
            The default configuration object.
        """
        if not self._default_config:
            self._load_default_config()
            reload_sandbox_policy()
        return self._default_config
    
    def get_user_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get the user configuration.

        If user_id is None, return the default configuration as a plain dict.

        Args:
            user_id: Optional user ID.

        Returns:
            User configuration as a dictionary.
        """
        if not user_id:
            if not self._default_config:
                self._load_default_config()
            default_payload = self._default_config.model_dump() if self._default_config else {}
            return self._migrate_payload(default_payload, warning_key="default")

        if user_id in self._user_config_cache:
            return self._user_config_cache[user_id]

        try:
            user_config = user_manager.get_user_config(user_id)
            merged_config = self._merge_configs(user_id, user_config)
            merged_config = self._migrate_payload(merged_config, warning_key=user_id)
            self._user_config_cache[user_id] = merged_config
            return merged_config
        except Exception as e:
            logger.error(f"ConfigService: Failed to get user config for {user_id}: {e}")
            if not self._default_config:
                self._load_default_config()
            default_payload = self._default_config.model_dump() if self._default_config else {}
            return self._migrate_payload(default_payload, warning_key="default")

    def get_merged_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get the merged configuration (default + user + environment).
        
        Precedence: environment vars > user config > default config.
        
        Args:
            user_id: Optional user ID.
            
        Returns:
            Merged configuration as a dictionary.
        """
        # 1. Start from the default configuration
        if not self._default_config:
            self._load_default_config()
            reload_sandbox_policy()
        
        default_dict = self._default_config.model_dump() if self._default_config else {}
        
        # 2. If we have a user ID, merge user configuration
        if user_id:
            user_config = user_manager.get_user_config(user_id) if user_id else {}
            # Deep-merge user configuration into the default configuration
            merged = self._deep_merge(default_dict.copy(), user_config)
        else:
            merged = default_dict.copy()
        
        # 3. Environment variables have highest priority (handled by load_config)
        # No extra handling here because PrometheaConfig already reads env vars
        
        return self._migrate_payload(merged, warning_key=(user_id or "default"))

    def _merge_configs(self, user_id: str, user_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge default configuration with a specific user's configuration.
        
        Args:
            user_id: User ID.
            user_config: User configuration dictionary.
            
        Returns:
            The merged configuration dictionary.
        """
        if not self._default_config:
            self._load_default_config()
            reload_sandbox_policy()
        
        default_dict = self._default_config.model_dump() if self._default_config else {}
        return self._deep_merge(default_dict.copy(), user_config)
    
    @staticmethod
    def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
        """Deep-merge two dictionaries in-place (source into target)."""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                ConfigService._deep_merge(target[key], value)
            else:
                target[key] = value
        return target
    
    def get_runtime_config(self, user_id: Optional[str] = None, scope: Optional[str] = None) -> Dict[str, Any]:
        merged = self.get_merged_config(user_id)
        runtime = {
            "config_version": merged.get("config_version", CURRENT_CONFIG_VERSION),
            "api": merged.get("api") or {},
            "memory": merged.get("memory") or {},
            "reasoning": merged.get("reasoning") or {},
            "sandbox": merged.get("sandbox") or {},
            "system": merged.get("system") or {},
            "runtime_config": merged.get("runtime_config") or {},
        }
        return self._scope_slice(runtime, scope)

    def get_user_preferences(self, user_id: str, scope: Optional[str] = None) -> Dict[str, Any]:
        merged = self.get_merged_config(user_id)
        preferences = merged.get("user_preferences") if isinstance(merged.get("user_preferences"), dict) else {}
        if not preferences:
            preferences = {
                "agent_name": merged.get("agent_name"),
                "system_prompt": merged.get("system_prompt"),
                "response_style": merged.get("response_style"),
                "skills": merged.get("skills") if isinstance(merged.get("skills"), dict) else {},
            }
        payload = {
            "config_version": merged.get("config_version", CURRENT_CONFIG_VERSION),
            "user_preferences": preferences,
        }
        return self._scope_slice(payload, scope)

    def get_tool_policy_config(self, user_id: Optional[str] = None, agent_id: Optional[str] = None) -> Dict[str, Any]:
        merged = self.get_merged_config(user_id)
        tools = merged.get("tools") if isinstance(merged.get("tools"), dict) else {}
        skills = merged.get("skills") if isinstance(merged.get("skills"), dict) else {}
        out = {
            "config_version": merged.get("config_version", CURRENT_CONFIG_VERSION),
            "agent_id": agent_id,
            "tools": tools,
            "skills": {
                "active": skills.get("active"),
                "overrides": skills.get("overrides") if isinstance(skills.get("overrides"), dict) else {},
            },
        }
        return out

    def get_channel_config(self, channel_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        merged = self.get_merged_config(user_id)
        channels = merged.get("channel_config") if isinstance(merged.get("channel_config"), dict) else {}
        if not isinstance(channels.get(channel_id), dict):
            return {}
        return dict(channels.get(channel_id) or {})

    # ===== Configuration update APIs =====
    
    async def update_user_config(
        self,
        params_or_user_id: Any,
        config_updates: Optional[Dict[str, Any]] = None,
        validate: bool = True,
        user_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Update a user's configuration.

        Returns:
            Result dict: {"success": bool, "message": str, "config": dict}.
        """
        try:
            if hasattr(params_or_user_id, "config_data"):
                params_obj = params_or_user_id
                user_id = user_id or kwargs.get("user_id")
                config_updates = getattr(params_obj, "config_data", {}) or {}
                validate = getattr(
                    params_obj,
                    "validate_config",
                    getattr(params_obj, "validate", validate),
                )
            else:
                user_id = params_or_user_id

            if not isinstance(user_id, str) or not user_id:
                return {"success": False, "message": "user_id is required", "config": {}}

            if config_updates is None:
                config_updates = {}

            current_config = user_manager.get_user_config(user_id)
            current_config = self._migrate_payload(current_config, warning_key=user_id)

            updated_config = self._deep_merge(current_config.copy(), config_updates)
            updated_config, migration_report = migrate_config(updated_config)

            persisted_updates = self._deep_merge(
                dict(config_updates),
                {"config_version": updated_config.get("config_version", CURRENT_CONFIG_VERSION)},
            )

            if validate:
                validation_result = self._validate_config(updated_config)
                if not validation_result["valid"]:
                    return {
                        "success": False,
                        "message": f"Configuration validation failed: {validation_result['error']}",
                        "config": current_config,
                        "migration": migration_report,
                    }

            success = user_manager.update_user_config_file(user_id, persisted_updates)
            if not success:
                return {
                    "success": False,
                    "message": "Failed to save user configuration",
                    "config": current_config,
                    "migration": migration_report,
                }

            if user_id in self._user_config_cache:
                del self._user_config_cache[user_id]
            reload_sandbox_policy()

            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.CONFIG_CHANGED,
                    {
                        "user_id": user_id,
                        "changes": config_updates,
                        "config": updated_config,
                    },
                )

            logger.info(f"ConfigService: User config updated for {user_id}")
            dep_warnings = sorted(
                set(self.get_deprecation_warnings(user_id) + list(migration_report.get("warnings") or []))
            )
            return {
                "success": True,
                "message": "Configuration updated successfully",
                "config": updated_config,
                "migration": migration_report,
                "warnings": dep_warnings,
            }

        except Exception as e:
            logger.error(f"ConfigService: Error updating user config: {e}")
            return {
                "success": False,
                "message": f"Failed to update config: {str(e)}",
                "config": {},
            }

    async def reset_user_config(
        self,
        user_id: str,
        reset_to_default: bool = True
    ) -> Dict[str, Any]:
        """
        Reset a user's configuration.
        
        Args:
            user_id: User ID.
            reset_to_default: If True, reset to default config; if False, clear user config.
            
        Returns:
            Result dict.
        """
        try:
            if reset_to_default:
                # Reset to default configuration while preserving user-specific fields like agent_name
                default_config = self.get_default_config().model_dump()
                default_config["config_version"] = CURRENT_CONFIG_VERSION
                # Preserve identity-related fields for the user
                current_config = user_manager.get_user_config(user_id)
                preserved_fields = {
                    "agent_name": current_config.get("agent_name", "Promethea"),
                }
                default_config.update(preserved_fields)
                
                # Save merged default configuration
                success = user_manager.update_user_config_file(user_id, default_config)
            else:
                # Clear configuration and keep only essential fields
                empty_config = {
                    "config_version": CURRENT_CONFIG_VERSION,
                    "agent_name": user_manager.get_user_config(user_id).get("agent_name", "Promethea"),
                    "system_prompt": "",
                    "api": {}
                }
                success = user_manager.update_user_config_file(user_id, empty_config)
            
            if not success:
                return {
                    "success": False,
                    "message": "Failed to reset configuration"
                }
            
            # Clear cache
            if user_id in self._user_config_cache:
                del self._user_config_cache[user_id]
            reload_sandbox_policy()
            
            # Emit configuration-changed event
            if self.event_emitter:
                await self.event_emitter.emit(EventType.CONFIG_CHANGED, {
                    "user_id": user_id,
                    "changes": {"reset": True},
                    "config": user_manager.get_user_config(user_id) if success else {}
                })
            
            logger.info(f"ConfigService: User config reset for {user_id}")
            
            return {
                "success": True,
                "message": "Configuration reset successfully"
            }
        
        except Exception as e:
            logger.error(f"ConfigService: Error resetting user config: {e}")
            return {
                "success": False,
                "message": f"Failed to reset configuration: {str(e)}"
            }
    
    # ===== Configuration hot-reload APIs =====
    
    async def reload_default_config(self) -> Dict[str, Any]:
        """
        Reload the default configuration (hot-reload).
        
        Returns:
            Result dict.
        """
        try:
            old_config = self._default_config.model_dump() if self._default_config else {}
            
            # Reload default configuration
            self._load_default_config()
            reload_sandbox_policy()
            
            new_config = self._default_config.model_dump() if self._default_config else {}
            
            # Emit configuration-reloaded event (affects all users)
            if self.event_emitter:
                await self.event_emitter.emit(EventType.CONFIG_RELOADED, {
                    "scope": "default",
                    "old_config": old_config,
                    "new_config": new_config
                })
            
            # Clear all user configuration cache entries (default config changed)
            self._user_config_cache.clear()
            
            logger.info("ConfigService: Default config reloaded")
            
            return {
                "success": True,
                "message": "Default configuration reloaded successfully",
                "config": new_config
            }
        
        except Exception as e:
            logger.error(f"ConfigService: Error reloading default config: {e}")
            return {
                "success": False,
                "message": f"Failed to reload configuration: {str(e)}"
            }
    
    # ===== Model switching and other advanced features =====
    
    async def switch_model(
        self,
        params_or_user_id: Any,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Switch the model for a given user.
        
        Args:
            user_id: User ID.
            model: Model name.
            api_key: Optional API key (if omitted, env/default is used).
            base_url: Optional base URL for the API.
            
        Returns:
            Result dict.
        """
        if hasattr(params_or_user_id, "model"):
            params_obj = params_or_user_id
            user_id = user_id or kwargs.get("user_id")
            model = getattr(params_obj, "model", None)
            api_key = getattr(params_obj, "api_key", api_key)
            base_url = getattr(params_obj, "base_url", base_url)
        else:
            user_id = params_or_user_id

        if not isinstance(user_id, str) or not user_id:
            return {"success": False, "message": "user_id is required", "config": {}}

        if not model:
            return {"success": False, "message": "model is required", "config": {}}

        if api_key:
            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.SECURITY_SECRET_ACCESS,
                    {
                        "user_id": user_id,
                        "request_id": kwargs.get("request_id"),
                        "namespace": "config",
                        "secret_field": "api.api_key",
                        "reason": "env_only_secret",
                        "outcome": "blocked",
                    },
                )
            return {
                "success": False,
                "message": "api_key is env-only; set API__API_KEY in .env",
                "config": {},
            }

        updates = {
            "api": {
                "model": model
            }
        }
        
        if base_url:
            updates["api"]["base_url"] = base_url
        
        return await self.update_user_config(user_id, updates, validate=True)
    
    async def update_system_prompt(
        self,
        user_id: str,
        system_prompt: str
    ) -> Dict[str, Any]:
        """
        Update the system prompt for a specific user.
        
        Args:
            user_id: User ID.
            system_prompt: New system prompt.
            
        Returns:
            Result dict.
        """
        return await self.update_user_config(
            user_id,
            {"system_prompt": system_prompt},
            validate=False  # System prompt does not require schema validation
        )
    
    async def update_agent_name(
        self,
        user_id: str,
        agent_name: str
    ) -> Dict[str, Any]:
        """
        Update the agent display name for a specific user.
        
        Args:
            user_id: User ID.
            agent_name: New agent name.
            
        Returns:
            Result dict.
        """
        return await self.update_user_config(
            user_id,
            {"agent_name": agent_name},
            validate=False
        )
    
    # ===== Configuration validation =====
    
    def _validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a configuration dictionary.

        Returns:
            {"valid": bool, "error": str or None}
        """
        try:
            if not isinstance(config, dict):
                return {"valid": False, "error": "config must be dict"}

            cfg_ver = str(config.get("config_version") or "").strip()
            if not cfg_ver:
                return {"valid": False, "error": "config_version is required"}

            # Validate known strict sections with Pydantic models while allowing
            # forward-compatible extra keys in other sections.
            PrometheaConfig(**config)
            return {"valid": True, "error": None}

        except Exception as e:
            return {"valid": False, "error": str(e)}

    def diagnose_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Diagnose configuration issues.
        
        Args:
            user_id: Optional user ID.
            
        Returns:
            Diagnostic result dictionary.
        """
        issues = []
        warnings = []
        
        # Get merged configuration
        config = self.get_merged_config(user_id)
        
        # Check API configuration
        api_config = config.get("api", {})
        if not api_config.get("api_key") or api_config.get("api_key") == "placeholder-key-not-set":
            issues.append("API key is not configured")
        
        if not api_config.get("model"):
            issues.append("Model is not configured")
        
        # Check memory system configuration
        memory_config = config.get("memory", {})
        if memory_config.get("enabled") and not memory_config.get("neo4j", {}).get("enabled"):
            warnings.append("Memory system is enabled but Neo4j is not enabled")
        memory_api = memory_config.get("api", {})
        if memory_config.get("enabled") and not memory_api.get("use_main_api", True):
            if not memory_api.get("api_key"):
                warnings.append("Memory API is configured as dedicated, but memory.api.api_key is empty")
            if not memory_api.get("base_url"):
                warnings.append("Memory API is configured as dedicated, but memory.api.base_url is empty")
            if not memory_api.get("model"):
                warnings.append("Memory API is configured as dedicated, but memory.api.model is empty")
        
        warnings.extend(self.get_deprecation_warnings(user_id))
        return {
            "user_id": user_id,
            "issues": issues,
            "warnings": sorted(set(warnings)),
            "config": config
        }













