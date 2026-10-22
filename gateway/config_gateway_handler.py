"""Configuration request adaptation; ConfigService remains the state owner."""

from __future__ import annotations

from typing import Callable, Optional, Dict, Any

from loguru import logger

from .config_protocol import normalize_config_update_params
from .config_service import ConfigService
from .connection import Connection
from .protocol import GatewayProtocol, RequestMessage, ResponseMessage
from .server_runtime_utils import resolve_request_user_id


class ConfigGatewayHandler:
    def __init__(self, get_service: Callable[[], Optional[ConfigService]]) -> None:
        self._get_service = get_service

    async def get(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle configuration fetch for current user."""
        try:
            config_service = self._get_service()
            if not config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )

            user_id = resolve_request_user_id(connection, request)
            config_data = config_service.get_merged_config(user_id)

            return GatewayProtocol.create_response(request.id, True, config_data)
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))

    async def reload(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle reload of default configuration."""
        try:
            config_service = self._get_service()
            if not config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )

            # Reload default config from disk.
            result = await config_service.reload_default_config()

            if result["success"]:
                return GatewayProtocol.create_response(
                    request.id,
                    True,
                    {
                        "status": "reloaded",
                        "message": result["message"],
                        "config": result.get("config", {}),
                    },
                )
            return GatewayProtocol.create_response(
                request.id, False, error=result["message"]
            )
        except Exception as e:
            logger.error(f"Error reloading config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))

    async def update(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle user configuration update."""
        try:
            config_service = self._get_service()
            if not config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )

            user_id = resolve_request_user_id(connection, request)
            normalized = normalize_config_update_params(request.params or {})
            config_updates = normalized["config"]
            if not config_updates:
                return GatewayProtocol.create_response(
                    request.id, False, error="config updates are required"
                )

            result = await config_service.update_user_config(
                user_id,
                config_updates,
                validate=bool(normalized["validate"]),
            )
            if not result.get("success"):
                return GatewayProtocol.create_response(
                    request.id,
                    False,
                    error=result.get("message") or "config update failed",
                )

            hot_apply_payload: Dict[str, Any] = {"requested": bool(normalized["hot_apply"]), "success": False}
            if normalized["hot_apply"]:
                reload_result = await config_service.reload_default_config()
                hot_apply_payload["success"] = bool(reload_result.get("success"))
                hot_apply_payload["message"] = reload_result.get("message")
                if reload_result.get("reloaded_at"):
                    hot_apply_payload["reloaded_at"] = reload_result.get("reloaded_at")
            result["hot_apply"] = hot_apply_payload

            return GatewayProtocol.create_response(
                request.id,
                True,
                payload=result,
            )
        except Exception as e:
            logger.error(f"Error updating config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))

    async def reset(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle user configuration reset."""
        try:
            config_service = self._get_service()
            if not config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )

            user_id = resolve_request_user_id(connection, request)

            reset_to_default = request.params.get("reset_to_default", True)

            result = await config_service.reset_user_config(user_id, reset_to_default)

            return GatewayProtocol.create_response(
                request.id,
                result["success"],
                payload=result if result["success"] else None,
                error=result.get("message") if not result["success"] else None
            )
        except Exception as e:
            logger.error(f"Error resetting config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))

    async def switch_model(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle switching of underlying LLM model for current user."""
        try:
            config_service = self._get_service()
            if not config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )

            user_id = resolve_request_user_id(connection, request)

            model = request.params.get("model")
            if not model:
                return GatewayProtocol.create_response(
                    request.id, False, error="model is required"
                )

            api_key = request.params.get("api_key")
            base_url = request.params.get("base_url")

            result = await config_service.switch_model(user_id, model, api_key, base_url)

            return GatewayProtocol.create_response(
                request.id,
                result["success"],
                payload=result if result["success"] else None,
                error=result.get("message") if not result["success"] else None
            )
        except Exception as e:
            logger.error(f"Error switching model: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))

    async def diagnose(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle configuration diagnostics for current user."""
        try:
            config_service = self._get_service()
            if not config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )

            user_id = resolve_request_user_id(connection, request)

            result = config_service.diagnose_config(user_id)

            return GatewayProtocol.create_response(request.id, True, result)
        except Exception as e:
            logger.error(f"Error diagnosing config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
