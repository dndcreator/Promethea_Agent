"""
Gateway integration module.

Wires gateway runtime, services, channels, and plugin system.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from channels import ChannelRegistry, MessageRouter
from computer import (
    BrowserController,
    FileSystemController,
    ProcessController,
    ScreenController,
)
from core.plugins.loader import PluginLoadOptions, load_promethea_plugins
from core.plugins.runtime import get_active_plugin_registry
from gateway import EventType, GatewayServer
from gateway.config_service import ConfigService
from gateway.conversation_service import ConversationService
from gateway.memory_service import MemoryService


class GatewayIntegration:
    """Gateway integration facade."""

    def __init__(self, config_path: str = "gateway_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()

        self.gateway_server: Optional[GatewayServer] = None
        self.channel_registry: Optional[ChannelRegistry] = None
        self.message_router: Optional[MessageRouter] = None

        # Computer controllers
        self.computer_controllers = {
            "browser": BrowserController(),
            "screen": ScreenController(),
            "filesystem": FileSystemController(),
            "process": ProcessController(),
        }

        # External dependencies (injected later)
        self.agent_manager = None
        self.memory_system = None
        self.conversation_core = None
        self.message_manager = None
        self.mcp_manager = None

    def _load_config(self) -> Dict[str, Any]:
        """Load gateway runtime config."""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}, using defaults")
            base = {
                "gateway": {"enabled": True, "host": "127.0.0.1", "port": 18789},
                "channels": {"web": {"enabled": True, "type": "web"}},
            }
            return self._apply_env_overrides(base)

        with open(self.config_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        return self._apply_env_overrides(loaded)

    def _apply_env_overrides(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Apply env override precedence: env > gateway_config.json > defaults."""
        result = dict(cfg or {})
        gw = dict(result.get("gateway") or {})
        http = dict(result.get("http") or {})
        rate = dict(http.get("rate_limit") or {})

        host = os.getenv("GATEWAY__HOST")
        if host:
            gw["host"] = host
        port = os.getenv("GATEWAY__PORT")
        if port:
            try:
                gw["port"] = int(port)
            except Exception:
                pass
        enabled = os.getenv("GATEWAY__ENABLED")
        if enabled:
            gw["enabled"] = enabled.lower() in {"1", "true", "yes"}
        result["gateway"] = gw

        rl_req = os.getenv("HTTP__RATE_LIMIT__REQUESTS")
        if rl_req:
            try:
                rate["requests"] = int(rl_req)
            except Exception:
                pass
        rl_win = os.getenv("HTTP__RATE_LIMIT__WINDOW_SECONDS")
        if rl_win:
            try:
                rate["window_seconds"] = int(rl_win)
            except Exception:
                pass
        if rate:
            http["rate_limit"] = rate
        if http:
            result["http"] = http
        return result

    async def reload_config(self) -> Dict[str, Any]:
        """Hot-reload gateway runtime config."""
        old_config = self.config
        self.config = self._load_config()
        if self.gateway_server and self.gateway_server.event_emitter:
            await self.gateway_server.event_emitter.emit(
                EventType.CONFIG_RELOADED,
                {
                    "scope": "gateway_runtime",
                    "old_config": old_config,
                    "new_config": self.config,
                },
            )
        return {"success": True, "config": self.config}

    def inject_dependencies(
        self,
        agent_manager=None,
        memory_system=None,
        conversation_core=None,
        message_manager=None,
        mcp_manager=None,
    ):
        """Inject external dependencies into gateway and services."""
        self.agent_manager = agent_manager
        self.memory_system = memory_system
        self.conversation_core = conversation_core
        self.message_manager = message_manager
        self.mcp_manager = mcp_manager

        if not self.gateway_server:
            return

        self.gateway_server.agent_manager = agent_manager
        self.gateway_server.message_manager = message_manager
        self.gateway_server.mcp_manager = mcp_manager
        self.gateway_server.computer_service = self

        event_emitter = self.gateway_server.event_emitter
        self.gateway_server.config_service = ConfigService(event_emitter=event_emitter)

        if not self.gateway_server.tool_service:
            from gateway.tool_service import ToolService

            self.gateway_server.tool_service = ToolService(event_emitter)

        memory_adapter = memory_system
        self.gateway_server.memory_service = MemoryService(
            event_emitter=event_emitter,
            memory_adapter=memory_adapter,
            llm_client=conversation_core,
            config_service=self.gateway_server.config_service,
        )
        self.gateway_server.memory_system = memory_adapter

        self.gateway_server.conversation_service = ConversationService(
            event_emitter=event_emitter,
            conversation_core=conversation_core,
            memory_service=self.gateway_server.memory_service,
            message_manager=message_manager,
            config_service=self.gateway_server.config_service,
        )
        self.gateway_server.conversation_core = conversation_core
        event_emitter.on(EventType.CONVERSATION_COMPLETE, self._on_conversation_complete)

        logger.info("Dependencies injected into gateway (with service layer)")

    async def initialize(self) -> bool:
        """Initialize gateway system."""
        try:
            logger.info("Initializing gateway system...")

            plugins_config = {"plugins": {}}
            channels_cfg = self.config.get("channels", {}) or {}
            for channel_id, ch_cfg in channels_cfg.items():
                plugins_config["plugins"][channel_id] = {
                    "enabled": bool(ch_cfg.get("enabled", False)),
                    "config": {"channel_config": ch_cfg},
                }

            try:
                from config import config as global_config

                mem_enabled = bool(getattr(global_config.memory, "enabled", False))
            except Exception:
                mem_enabled = False

            plugins_config["plugins"]["memory"] = {
                "enabled": mem_enabled,
                "config": {},
            }

            load_promethea_plugins(
                PluginLoadOptions(
                    workspace_dir=str(Path(__file__).resolve().parent),
                    extensions_dir="extensions",
                    config=plugins_config,
                    cache=True,
                    mode="full",
                    allow=None,
                )
            )

            self.gateway_server = GatewayServer()
            self.inject_dependencies(
                agent_manager=self.agent_manager,
                memory_system=self.memory_system,
                conversation_core=self.conversation_core,
                message_manager=self.message_manager,
                mcp_manager=self.mcp_manager,
            )

            self.channel_registry = ChannelRegistry()
            self.message_router = MessageRouter(self.channel_registry)
            self.gateway_server.channels = {}

            await self._init_channels()

            computer_cfg = self.config.get("computer", {})
            enabled = computer_cfg.get(
                "enabled_controllers",
                ["browser", "screen", "filesystem", "process"],
            )
            for name, controller in self.computer_controllers.items():
                if name not in enabled:
                    logger.info(f"Computer controller '{name}' is disabled")
                    continue
                try:
                    ok = await controller.initialize()
                    if ok:
                        logger.info(f"Computer controller '{name}' initialized successfully")
                    else:
                        logger.warning(f"Computer controller '{name}' failed to initialize")
                except Exception as e:
                    logger.error(f"Error initializing computer controller '{name}': {e}")

            self.message_router.setup_channel_listeners()
            self.message_router.register_global_handler(self._handle_incoming_message)

            await self.gateway_server.start()
            logger.info("Gateway system initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize gateway: {e}")
            return False

    async def _init_channels(self):
        """Initialize channels from plugin runtime registry."""
        registry = get_active_plugin_registry()
        if not registry or not registry.channels:
            logger.warning("No channel plugins loaded from extensions/")
            return

        auto_start = self.config.get("gateway", {}).get("auto_start_channels", True)
        for entry in registry.channels:
            try:
                channel_id = entry.channel_id
                channel = entry.channel
                self.channel_registry.register(channel)
                self.gateway_server.channels[channel_id] = channel
                if auto_start:
                    await channel.start()
                logger.info(
                    f"Initialized channel from extension: {channel_id} "
                    f"(source={entry.source})"
                )
            except Exception as e:
                logger.error(
                    f"Failed to initialize channel from extension {entry.channel_id}: {e}"
                )

    async def _on_conversation_complete(self, event_msg):
        """Send conversation result back to channel."""
        try:
            payload = event_msg.payload
            channel = payload.get("channel")
            response = payload.get("response", "")
            sender = payload.get("user_id")
            if not response or not channel:
                return
            await self.message_router.send_message(
                channel_name=channel,
                receiver_id=sender,
                content=response,
            )
        except Exception as e:
            logger.error(f"Error sending reply to channel: {e}")

    async def _handle_incoming_message(self, message):
        """Handle incoming channel message."""
        try:
            if not self.gateway_server:
                return
            payload = {
                "channel": message.channel.value,
                "sender": message.sender_name or message.sender_id,
                "content": message.content,
                "message_type": message.message_type.value,
                "timestamp": message.timestamp.isoformat(),
            }
            await self.gateway_server.event_emitter.emit(EventType.CHANNEL_MESSAGE, payload)
            await self.gateway_server.connection_manager.broadcast(
                EventType.CHANNEL_MESSAGE,
                payload,
            )
            if not self.gateway_server.conversation_service:
                logger.warning(
                    "ConversationService not initialized, message will not be processed"
                )
        except Exception as e:
            logger.error(f"Error handling incoming message: {e}")

    async def shutdown(self):
        """Shutdown gateway system."""
        try:
            logger.info("Shutting down gateway system...")
            for name, controller in self.computer_controllers.items():
                try:
                    await controller.cleanup()
                    logger.info(f"Computer controller '{name}' cleaned up")
                except Exception as e:
                    logger.error(f"Error cleaning up computer controller '{name}': {e}")

            if self.gateway_server:
                await self.gateway_server.stop()
            logger.info("Gateway system shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    def get_gateway_server(self) -> GatewayServer:
        """Return gateway server instance."""
        return self.gateway_server

    def get_channel_registry(self) -> ChannelRegistry:
        """Return channel registry."""
        return self.channel_registry

    def get_message_router(self) -> MessageRouter:
        """Return message router."""
        return self.message_router

    async def execute_computer_action(self, capability: str, action: str, params: Dict[str, Any]):
        """Execute computer control action."""
        from computer.base import ComputerResult

        if capability not in self.computer_controllers:
            return ComputerResult(success=False, error=f"Unknown capability: {capability}")

        controller = self.computer_controllers[capability]
        if not controller.is_initialized:
            return ComputerResult(
                success=False,
                error=f"Controller '{capability}' is not initialized",
            )
        return await controller.execute(action, params)

    def get_computer_status(self) -> Dict[str, Any]:
        """Return status for all computer controllers."""
        return {name: ctl.get_status() for name, ctl in self.computer_controllers.items()}


_gateway_integration: Optional[GatewayIntegration] = None


async def initialize_gateway(
    config_path: str = "gateway_config.json",
    agent_manager=None,
    memory_system=None,
    conversation_core=None,
    message_manager=None,
    mcp_manager=None,
) -> GatewayIntegration:
    """Initialize gateway singleton."""
    global _gateway_integration
    if _gateway_integration is None:
        _gateway_integration = GatewayIntegration(config_path)
        _gateway_integration.inject_dependencies(
            agent_manager,
            memory_system,
            conversation_core,
            message_manager,
            mcp_manager,
        )
        await _gateway_integration.initialize()
    return _gateway_integration


def get_gateway_integration() -> Optional[GatewayIntegration]:
    """Get gateway singleton instance."""
    return _gateway_integration

