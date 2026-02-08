from __future__ import annotations

"""
配置系统服务层

目标：
- 把 Gateway 中的"配置"能力抽象成一个独立的 ConfigService
- 管理默认配置、用户配置、环境变量（敏感信息）
- 提供配置的创建、更新、查询、重置、热重载功能
- 通过事件总线发出配置变更事件，让其他服务自动响应
- 作为模型切换等功能的总集成入口
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
    配置服务（对 Gateway 暴露的统一入口）

    - 管理三层配置：默认配置、用户配置、环境变量
    - 提供配置的创建、更新、查询、重置、热重载
    - 在 EventEmitter 上发出 CONFIG_* 事件，让其他服务自动响应配置变更
    - 作为模型切换等功能的总集成入口
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
        """加载默认配置（系统级）"""
        try:
            self._default_config = load_config()
            logger.info("ConfigService: Default config loaded")
        except Exception as e:
            logger.error(f"ConfigService: Failed to load default config: {e}")
            # 使用空配置作为降级
            self._default_config = PrometheaConfig()
    
    # ===== 配置查询 API =====
    
    def get_default_config(self) -> PrometheaConfig:
        """
        获取默认配置（系统级）
        
        Returns:
            默认配置对象
        """
        if not self._default_config:
            self._load_default_config()
        return self._default_config
    
    def get_user_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取用户配置（如果 user_id 为 None，返回默认配置的字典形式）
        
        Args:
            user_id: 用户ID（可选）
            
        Returns:
            用户配置字典
        """
        if not user_id:
            # 返回默认配置的字典形式
            if not self._default_config:
                self._load_default_config()
            return self._default_config.model_dump() if self._default_config else {}
        
        # 检查缓存
        if user_id in self._user_config_cache:
            return self._user_config_cache[user_id]
        
        # 从 user_manager 加载用户配置
        try:
            user_config = user_manager.get_user_config(user_id)
            # 合并默认配置和用户配置
            merged_config = self._merge_configs(user_id, user_config)
            # 缓存
            self._user_config_cache[user_id] = merged_config
            return merged_config
        except Exception as e:
            logger.error(f"ConfigService: Failed to get user config for {user_id}: {e}")
            # 降级：返回默认配置
            if not self._default_config:
                self._load_default_config()
            return self._default_config.model_dump() if self._default_config else {}
    
    def get_merged_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取合并后的配置（默认配置 + 用户配置 + 环境变量）
        
        优先级：环境变量 > 用户配置 > 默认配置
        
        Args:
            user_id: 用户ID（可选）
            
        Returns:
            合并后的配置字典
        """
        # 1. 从默认配置开始
        if not self._default_config:
            self._load_default_config()
        
        default_dict = self._default_config.model_dump() if self._default_config else {}
        
        # 2. 如果有用户ID，合并用户配置
        if user_id:
            user_config = user_manager.get_user_config(user_id) if user_id else {}
            # 深度合并用户配置到默认配置
            merged = self._deep_merge(default_dict.copy(), user_config)
        else:
            merged = default_dict.copy()
        
        # 3. 环境变量优先级最高（已经在 load_config 中处理了）
        # 这里不需要再次处理，因为 PrometheaConfig 已经读取了环境变量
        
        return merged
    
    def _merge_configs(self, user_id: str, user_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        合并默认配置和用户配置
        
        Args:
            user_id: 用户ID
            user_config: 用户配置字典
            
        Returns:
            合并后的配置字典
        """
        if not self._default_config:
            self._load_default_config()
        
        default_dict = self._default_config.model_dump() if self._default_config else {}
        return self._deep_merge(default_dict.copy(), user_config)
    
    @staticmethod
    def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
        """深度合并字典"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                ConfigService._deep_merge(target[key], value)
            else:
                target[key] = value
        return target
    
    # ===== 配置更新 API =====
    
    async def update_user_config(
        self,
        user_id: str,
        config_updates: Dict[str, Any],
        validate: bool = True
    ) -> Dict[str, Any]:
        """
        更新用户配置
        
        Args:
            user_id: 用户ID
            config_updates: 要更新的配置项（支持嵌套，如 {"api": {"model": "..."}}）
            validate: 是否验证配置
            
        Returns:
            更新结果 {"success": bool, "message": str, "config": dict}
        """
        try:
            # 1. 获取当前用户配置
            current_config = user_manager.get_user_config(user_id)
            
            # 2. 深度合并更新
            updated_config = self._deep_merge(current_config.copy(), config_updates)
            
            # 3. 验证配置（如果启用）
            if validate:
                validation_result = self._validate_config(updated_config)
                if not validation_result["valid"]:
                    return {
                        "success": False,
                        "message": f"配置验证失败: {validation_result['error']}",
                        "config": current_config
                    }
            
            # 4. 保存到文件
            success = user_manager.update_user_config_file(user_id, config_updates)
            
            if not success:
                return {
                    "success": False,
                    "message": "保存用户配置失败",
                    "config": current_config
                }
            
            # 5. 清除缓存
            if user_id in self._user_config_cache:
                del self._user_config_cache[user_id]
            
            # 6. 发出配置变更事件
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
                "message": f"更新配置失败: {str(e)}",
                "config": {}
            }
    
    async def reset_user_config(
        self,
        user_id: str,
        reset_to_default: bool = True
    ) -> Dict[str, Any]:
        """
        重置用户配置
        
        Args:
            user_id: 用户ID
            reset_to_default: 是否重置为默认配置（True）或清空（False）
            
        Returns:
            重置结果
        """
        try:
            if reset_to_default:
                # 重置为默认配置（保留用户特定的字段，如 agent_name）
                default_config = self.get_default_config().model_dump()
                # 保留用户身份相关的字段
                current_config = user_manager.get_user_config(user_id)
                preserved_fields = {
                    "agent_name": current_config.get("agent_name", "Promethea"),
                }
                default_config.update(preserved_fields)
                
                # 保存
                success = user_manager.update_user_config_file(user_id, default_config)
            else:
                # 清空配置（只保留必要字段）
                empty_config = {
                    "agent_name": user_manager.get_user_config(user_id).get("agent_name", "Promethea"),
                    "system_prompt": "",
                    "api": {}
                }
                success = user_manager.update_user_config_file(user_id, empty_config)
            
            if not success:
                return {
                    "success": False,
                    "message": "重置配置失败"
                }
            
            # 清除缓存
            if user_id in self._user_config_cache:
                del self._user_config_cache[user_id]
            
            # 发出配置变更事件
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
                "message": f"重置配置失败: {str(e)}"
            }
    
    # ===== 配置热重载 API =====
    
    async def reload_default_config(self) -> Dict[str, Any]:
        """
        重新加载默认配置（热重载）
        
        Returns:
            重载结果
        """
        try:
            old_config = self._default_config.model_dump() if self._default_config else {}
            
            # 重新加载
            self._load_default_config()
            
            new_config = self._default_config.model_dump() if self._default_config else {}
            
            # 发出配置变更事件（影响所有用户）
            if self.event_emitter:
                await self.event_emitter.emit(EventType.CONFIG_RELOADED, {
                    "scope": "default",
                    "old_config": old_config,
                    "new_config": new_config
                })
            
            # 清除所有用户配置缓存（因为默认配置变了）
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
                "message": f"重载配置失败: {str(e)}"
            }
    
    # ===== 模型切换等高级功能 =====
    
    async def switch_model(
        self,
        user_id: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        切换模型（用户级）
        
        Args:
            user_id: 用户ID
            model: 模型名称
            api_key: API密钥（可选，如果不提供则使用环境变量或默认值）
            base_url: API基础URL（可选）
            
        Returns:
            切换结果
        """
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
        更新系统提示词（用户级）
        
        Args:
            user_id: 用户ID
            system_prompt: 新的系统提示词
            
        Returns:
            更新结果
        """
        return await self.update_user_config(
            user_id,
            {"system_prompt": system_prompt},
            validate=False  # 系统提示词不需要验证
        )
    
    async def update_agent_name(
        self,
        user_id: str,
        agent_name: str
    ) -> Dict[str, Any]:
        """
        更新 Agent 名称（用户级）
        
        Args:
            user_id: 用户ID
            agent_name: 新的 Agent 名称
            
        Returns:
            更新结果
        """
        return await self.update_user_config(
            user_id,
            {"agent_name": agent_name},
            validate=False
        )
    
    # ===== 配置验证 =====
    
    def _validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证配置有效性
        
        Args:
            config: 配置字典
            
        Returns:
            {"valid": bool, "error": str}
        """
        try:
            # 尝试用 Pydantic 模型验证
            # 只验证 API 配置部分
            if "api" in config:
                from config import APIConfig
                api_config = APIConfig(**config["api"])
                # 验证通过
                return {"valid": True, "error": None}
            
            return {"valid": True, "error": None}
        
        except Exception as e:
            return {"valid": False, "error": str(e)}
    
    # ===== 配置诊断 =====
    
    def diagnose_config(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        诊断配置问题
        
        Args:
            user_id: 用户ID（可选）
            
        Returns:
            诊断结果
        """
        issues = []
        warnings = []
        
        # 获取配置
        config = self.get_merged_config(user_id)
        
        # 检查 API 配置
        api_config = config.get("api", {})
        if not api_config.get("api_key") or api_config.get("api_key") == "placeholder-key-not-set":
            issues.append("API密钥未配置")
        
        if not api_config.get("model"):
            issues.append("模型未配置")
        
        # 检查记忆系统配置
        memory_config = config.get("memory", {})
        if memory_config.get("enabled") and not memory_config.get("neo4j", {}).get("enabled"):
            warnings.append("记忆系统已启用但 Neo4j 未启用")
        
        return {
            "user_id": user_id,
            "issues": issues,
            "warnings": warnings,
            "config": config
        }
