from __future__ import annotations

from fastapi import APIRouter, HTTPException
import json
import logging
from pathlib import Path

import config as config_module

from .. import state


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/metrics")
async def get_metrics():
    """获取性能统计数据"""
    return {"status": "success", "metrics": state.metrics.get_stats()}


@router.get("/config")
async def get_config():
    """获取当前配置（可热修改的部分）"""
    try:
        cfg = config_module.load_config()

        return {
            "status": "success",
            "config": {
                "api": {
                    "api_key": cfg.api.api_key[:20] + "..." if len(cfg.api.api_key) > 20 else cfg.api.api_key,
                    "base_url": cfg.api.base_url,
                    "model": cfg.api.model,
                    "temperature": cfg.api.temperature,
                    "max_tokens": cfg.api.max_tokens,
                    "max_history_rounds": cfg.api.max_history_rounds,
                },
                "system": {
                    "stream_mode": cfg.system.stream_mode,
                    "debug": cfg.system.debug,
                    "log_level": cfg.system.log_level,
                },
                "memory": {
                    "enabled": cfg.memory.enabled,
                    "neo4j": {
                        "enabled": cfg.memory.neo4j.enabled,
                        "uri": cfg.memory.neo4j.uri,
                        "username": cfg.memory.neo4j.username,
                        "database": cfg.memory.neo4j.database,
                    },
                    "warm_layer": {
                        "enabled": cfg.memory.warm_layer.enabled,
                        "clustering_threshold": cfg.memory.warm_layer.clustering_threshold,
                        "min_cluster_size": cfg.memory.warm_layer.min_cluster_size,
                    },
                    "cold_layer": {
                        "max_summary_length": cfg.memory.cold_layer.max_summary_length,
                        "compression_threshold": cfg.memory.cold_layer.compression_threshold,
                    },
                },
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.post("/config")
async def update_config(request: dict):
    """更新配置（热修改）"""
    try:
        # 优先使用 config/default.json，如果不存在则使用根目录的 config.json（向后兼容）
        config_path = Path("config/default.json")
        if not config_path.exists():
            # 优先使用 config/default.json，如果不存在则使用根目录的 config.json（向后兼容）
        config_path = Path("config/default.json")
        if not config_path.exists():
            config_path = Path("config.json")

        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                current_config = json.load(f)
        else:
            # 如果都不存在，使用默认配置
            from config import PrometheaConfig
            current_config = PrometheaConfig().model_dump()

        def deep_update(base_dict, update_dict):
            for key, value in update_dict.items():
                if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
                    deep_update(base_dict[key], value)
                else:
                    base_dict[key] = value

        deep_update(current_config, request.get("config", {}))

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(current_config, f, indent=4, ensure_ascii=False)

        # 触发热重载（行为保持不变：更新 config_module.config 全局对象）
        global_config = config_module.load_config()
        config_module.config = global_config  # type: ignore[attr-defined]

        # 重新初始化会话核心（使用新配置）
        from conversation_core import PrometheaConversation

        state.conversation = PrometheaConversation()  # type: ignore[misc]

        logger.info("✅ 配置已更新并热重载")

        return {"status": "success", "message": "配置已更新并生效"}

    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")

