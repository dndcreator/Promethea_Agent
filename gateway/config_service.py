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
from api_server.user_manager import user_manager


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
        
        # 默认配置（系统级，从 config.py 加载）
        self._default_config: Optional[PrometheaConfig] = None
        
        # 配置缓存（用户ID -> 合并后的配置）
        self._user_config_cache: Dict[str, Dict[str, Any]] = {}
        
        # 初始化默认配置
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
    
    # ===== Configuration query APIs =====
    
    def get_default_config(self) -> PrometheaConfig:
        """
        Get the default (system-level) configuration.
        
        Returns:
            The default configuration object.
        """
        if not self._default_config:
            self._load_default_config()
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
            # Return the default configuration as a dictionary
            if not self._default_config:
                self._load_default_config()
            return self._default_config.model_dump() if self._default_config else {}
        
        # Check cache first
        if user_id in self._user_config_cache:
            return self._user_config_cache[user_id]
        
        # Load user config from user_manager
        try:
            user_config = user_manager.get_user_config(user_id)
            # Merge default config and user config
            merged_config = self._merge_configs(user_id, user_config)
            # Cache the merged result
            self._user_config_cache[user_id] = merged_config
            return merged_config
        except Exception as e:
            logger.error(f"ConfigService: Failed to get user config for {user_id}: {e}")
            # Fallback: return default configuration
            if not self._default_config:
                self._load_default_config()
            return self._default_config.model_dump() if self._default_config else {}
    
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
        
        return merged
    
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
        
        Args:
            user_id: User ID.
            config_updates: Configuration fields to update (supports nesting, e.g. {"api": {"model": "..."}}).
            validate: Whether to validate the updated configuration.
            
        Returns:
            Result dict: {"success": bool, "message": str, "config": dict}.
        """
        try:
            # 1. Get current user configuration
            if hasattr(params_or_user_id, "config_data"):
                params_obj = params_or_user_id
                user_id = user_id or kwargs.get("user_id")
                config_updates = getattr(params_obj, "config_data", {}) or {}
                validate = getattr(params_obj, "validate", validate)
            else:
                user_id = params_or_user_id

            if not isinstance(user_id, str) or not user_id:
                return {"success": False, "message": "user_id is required", "config": {}}

            if config_updates is None:
                config_updates = {}

            current_config = user_manager.get_user_config(user_id)
            
            # 2. Apply a deep-merge of the updates
            updated_config = self._deep_merge(current_config.copy(), config_updates)
            
            # 3. Optionally validate the configuration
            if validate:
                validation_result = self._validate_config(updated_config)
                if not validation_result["valid"]:
                    return {
                        "success": False,
                        "message": f"配置验证失败: {validation_result['error']}",
                        "config": current_config
                    }
            
            # 4. Persist updates to disk
            success = user_manager.update_user_config_file(user_id, config_updates)
            
            if not success:
                return {
                    "success": False,
                    "message": "保存用户配置失败",
                    "config": current_config
                }
            
            # 5. Clear cache
            if user_id in self._user_config_cache:
                del self._user_config_cache[user_id]
            
            # 6. Emit configuration-changed event
            if self.event_emitter:
                await self.event_emitter.emit(EventType.CONFIG_CHANGED, {
                    "user_id": user_id,
                    "changes": config_updates,
                    "config": updated_config
                })
            
            logger.info(f"ConfigService: User config updated for {user_id}")
            
            return {
                "success": True,
                "message": "配置更新成功",
                "config": updated_config
            }
        
        except Exception as e:
            logger.error(f"ConfigService: Error updating user config: {e}")
            return {
                "success": False,
                "message": f"Failed to update config: {str(e)}",
                "config": {}
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
                "message": "配置重置成功"
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
                "message": "默认配置重载成功",
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

        updates = {
            "api": {
                "model": model
            }
        }
        
        if api_key:
            updates["api"]["api_key"] = api_key
        
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
        
        Args:
            config: Configuration dictionary.
            
        Returns:
            {"valid": bool, "error": str or None}
        """
        try:
            # Try to validate with the Pydantic model.
            # Only validate the API configuration section.
            if "api" in config:
                from config import APIConfig
                api_config = APIConfig(**config["api"])
                # Validation succeeded
                return {"valid": True, "error": None}
            
            return {"valid": True, "error": None}
        
        except Exception as e:
            return {"valid": False, "error": str(e)}
    
    # ===== Configuration diagnostics =====
    
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
        
        return {
            "user_id": user_id,
            "issues": issues,
            "warnings": warnings,
            "config": config
        }
