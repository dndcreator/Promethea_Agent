"""
网关集成模块 - 将网关系统与现有功能集成
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger

from gateway import GatewayServer, EventType
from gateway.memory_service import MemoryService
from gateway.conversation_service import ConversationService
from gateway.config_service import ConfigService
from channels import (
    ChannelRegistry, MessageRouter, ChannelType, ChannelConfig
)
from gateway.connection import Connection
from computer import (
    BrowserController, ScreenController,
    FileSystemController, ProcessController
)

from core.plugins.loader import load_promethea_plugins, PluginLoadOptions
from core.plugins.runtime import get_active_plugin_registry

class GatewayIntegration:
    """网关集成类"""
    
    def __init__(self, config_path: str = "gateway_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        
        self.gateway_server: Optional[GatewayServer] = None
        self.channel_registry: Optional[ChannelRegistry] = None
        self.message_router: Optional[MessageRouter] = None
        
        # 电脑控制器
        self.computer_controllers = {
            'browser': BrowserController(),
            'screen': ScreenController(),
            'filesystem': FileSystemController(),
            'process': ProcessController()
        }
        
        # 外部依赖（稍后注入）
        self.agent_manager = None
        self.memory_system = None
        self.conversation_core = None
        self.message_manager = None
        
    def _load_config(self) -> Dict[str, Any]:
        """加载配置"""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}, using defaults")
            return {
                "gateway": {"enabled": True, "host": "127.0.0.1", "port": 18789},
                "channels": {"web": {"enabled": True, "type": "web"}}
            }
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def inject_dependencies(
        self,
        agent_manager=None,
        memory_system=None,
        conversation_core=None,
        message_manager=None
    ):
        """注入外部依赖"""
        self.agent_manager = agent_manager
        self.memory_system = memory_system
        self.conversation_core = conversation_core
        self.message_manager = message_manager
        
        if self.gateway_server:
            self.gateway_server.agent_manager = agent_manager
            self.gateway_server.message_manager = message_manager
            # 电脑控制服务：Gateway 只依赖一个抽象接口，这里直接用自身实现
            self.gateway_server.computer_service = self
            
            # 初始化三个一级服务（工具、记忆、对话）
            event_emitter = self.gateway_server.event_emitter
            
            # 1. 配置服务（最先初始化，其他服务可能依赖配置）
            self.gateway_server.config_service = ConfigService(event_emitter=event_emitter)
            
            # 2. 工具服务（已由 GatewayServer 初始化，这里确保存在）
            if not self.gateway_server.tool_service:
                from gateway.tool_service import ToolService
                self.gateway_server.tool_service = ToolService(event_emitter)
            
            # 3. 记忆服务
            memory_adapter = memory_system  # memory_system 就是 MemoryAdapter
            self.gateway_server.memory_service = MemoryService(
                event_emitter=event_emitter,
                memory_adapter=memory_adapter,
                llm_client=conversation_core,
                config_service=self.gateway_server.config_service,
            )
            # 向后兼容：保留旧属性名
            self.gateway_server.memory_system = memory_adapter
            
            # 4. 对话服务（注入 ConfigService 以便获取配置）
            self.gateway_server.conversation_service = ConversationService(
                event_emitter=event_emitter,
                conversation_core=conversation_core,
                memory_service=self.gateway_server.memory_service,
                message_manager=message_manager,
                config_service=self.gateway_server.config_service
            )
            # 向后兼容：保留旧属性名
            self.gateway_server.conversation_core = conversation_core
            # Route final replies back to channel
            event_emitter.on(EventType.CONVERSATION_COMPLETE, self._on_conversation_complete)
        
        logger.info("Dependencies injected into gateway (with service layer)")
    
    async def initialize(self) -> bool:
        """初始化网关系统"""
        try:
            logger.info("Initializing gateway system...")

            # 1) Moltbot-style: load extensions -> active plugin registry
            plugins_config = {"plugins": {}}

            # channel enable state from gateway_config.json
            channels_cfg = self.config.get("channels", {}) or {}
            for channel_id, ch_cfg in channels_cfg.items():
                plugins_config["plugins"][channel_id] = {
                    "enabled": bool(ch_cfg.get("enabled", False)),
                    "config": {"channel_config": ch_cfg},
                }

            # memory enable state from config.py
            try:
                from config import config as global_config
                mem_enabled = bool(getattr(global_config.memory, "enabled", False))
            except Exception:
                mem_enabled = False

            plugins_config["plugins"]["memory"] = {"enabled": mem_enabled, "config": {}}

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

            # 创建网关服务器
            self.gateway_server = GatewayServer()

            # 注入依赖（这会初始化服务层：ToolService, MemoryService, ConversationService）
            # 注意：inject_dependencies 必须在创建 gateway_server 之后调用
            self.inject_dependencies(
                agent_manager=self.agent_manager,
                memory_system=self.memory_system,
                conversation_core=self.conversation_core,
                message_manager=self.message_manager
            )
            
            # 创建通道注册表和路由器
            self.channel_registry = ChannelRegistry()
            self.message_router = MessageRouter(self.channel_registry)
            
            # 注册通道到网关
            self.gateway_server.channels = {}
            
            # 初始化通道 (via extensions registry)
            await self._init_channels()
            
            # 初始化电脑控制器
            computer_config = self.config.get("computer", {})
            enabled_controllers = computer_config.get("enabled_controllers", ["browser", "screen", "filesystem", "process"])
            logger.info(f"Initializing computer controllers: {enabled_controllers}")
            
            for name, controller in self.computer_controllers.items():
                if name not in enabled_controllers:
                    logger.info(f"Computer controller '{name}' is disabled")
                    continue
                
                try:
                    initialized = await controller.initialize()
                    if initialized:
                        logger.info(f"Computer controller '{name}' initialized successfully")
                    else:
                        logger.warning(f"Computer controller '{name}' failed to initialize")
                except Exception as e:
                    logger.error(f"Error initializing computer controller '{name}': {e}")
            
            # 设置路由器监听
            self.message_router.setup_channel_listeners()
            
            # 注册全局消息处理器
            self.message_router.register_global_handler(self._handle_incoming_message)
            
            # 启动网关
            await self.gateway_server.start()
            
            logger.info("Gateway system initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize gateway: {e}")
            return False
    
    async def _init_channels(self):
        """初始化所有通道"""
        registry = get_active_plugin_registry()
        if not registry or not registry.channels:
            logger.warning("No channel plugins loaded from extensions/")
            return

        auto_start = self.config.get("gateway", {}).get("auto_start_channels", True)

        for entry in registry.channels:
            try:
                channel_id = entry.channel_id
                channel = entry.channel

                # Register channel instance into legacy router/registry
                self.channel_registry.register(channel)
                self.gateway_server.channels[channel_id] = channel

                if auto_start:
                    await channel.start()

                logger.info(f"Initialized channel from extension: {channel_id} (source={entry.source})")

            except Exception as e:
                logger.error(f"Failed to initialize channel from extension {entry.channel_id}: {e}")
                import traceback
                traceback.print_exc()
    
    async def _on_conversation_complete(self, event_msg):
        """处理对话完成事件，发送回复给渠道"""
        try:
            payload = event_msg.payload
            channel = payload.get("channel")
            response = payload.get("response", "")
            sender = payload.get("user_id")  # user_id 就是 sender
            
            if not response or not channel:
                return
            
            # 发送回复给渠道
            logger.info(f"Sending reply to {channel}: {response[:50]}...")
            await self.message_router.send_message(
                channel_name=channel,
                recipient_id=sender,
                content=response
            )
        except Exception as e:
            logger.error(f"Error sending reply to channel: {e}")
    
    async def _handle_incoming_message(self, message):
        """处理接收到的消息"""
        try:
            logger.info(f"Received message from {message.channel}: {message.content[:100]}")
            
            # 广播到WebSocket客户端（调试用）
            # 同时，ConversationService 会订阅这个事件并自动处理对话
            if self.gateway_server:
                payload = {
                    "channel": message.channel.value,
                    "sender": message.sender_name or message.sender_id,
                    "content": message.content,
                    "message_type": message.message_type.value,
                    "timestamp": message.timestamp.isoformat()
                }
                # Push to internal event bus for services (ConversationService, etc.)
                await self.gateway_server.event_emitter.emit(
                    EventType.CHANNEL_MESSAGE,
                    payload,
                )
                # Broadcast to websocket clients for observability/debug UI.
                await self.gateway_server.connection_manager.broadcast(
                    EventType.CHANNEL_MESSAGE,
                    payload,
                )

            # ConversationService 已经订阅了 CHANNEL_MESSAGE 事件，会自动处理对话
            # _on_conversation_complete 会处理回复发送
            # 如果 ConversationService 未初始化，记录警告（不应该发生）
            if not (self.gateway_server and self.gateway_server.conversation_service):
                logger.warning("ConversationService not initialized, message will not be processed")
            
        except Exception as e:
            logger.error(f"Error handling incoming message: {e}")
            import traceback
            traceback.print_exc()
    
    async def shutdown(self):
        """关闭网关系统"""
        try:
            logger.info("Shutting down gateway system...")
            
            # 停止所有通道 (Handled by Kernel shutdown for plugins, but legacy registry might need it?)
            # Since ChannelPlugin.shutdown calls Channel.stop, Kernel shutdown is enough for channels loaded via Kernel.
            # But we should clear legacy registry to be safe.
            if self.channel_registry:
                # await self.channel_registry.stop_all() # Kernel will do this
                pass
            
            # 清理电脑控制器
            for name, controller in self.computer_controllers.items():
                try:
                    await controller.cleanup()
                    logger.info(f"Computer controller '{name}' cleaned up")
                except Exception as e:
                    logger.error(f"Error cleaning up computer controller '{name}': {e}")
            
            # 停止网关服务器
            if self.gateway_server:
                await self.gateway_server.stop()

            logger.info("Gateway system shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    def get_gateway_server(self) -> GatewayServer:
        """获取网关服务器实例"""
        return self.gateway_server
    
    def get_channel_registry(self) -> ChannelRegistry:
        """获取通道注册表"""
        return self.channel_registry
    
    def get_message_router(self) -> MessageRouter:
        """获取消息路由器"""
        return self.message_router
    
    async def execute_computer_action(
        self,
        capability: str,
        action: str,
        params: Dict[str, Any]
    ):
        """执行电脑控制操作"""
        from computer.base import ComputerResult
        
        if capability not in self.computer_controllers:
            return ComputerResult(
                success=False,
                error=f"Unknown capability: {capability}"
            )
        
        controller = self.computer_controllers[capability]
        if not controller.is_initialized:
            return ComputerResult(
                success=False,
                error=f"Controller '{capability}' is not initialized"
            )
        
        return await controller.execute(action, params)
    
    def get_computer_status(self) -> Dict[str, Any]:
        """获取所有电脑控制器状态"""
        status = {}
        for name, controller in self.computer_controllers.items():
            status[name] = controller.get_status()
        return status


# 全局实例
_gateway_integration: Optional[GatewayIntegration] = None


async def initialize_gateway(
    config_path: str = "gateway_config.json",
    agent_manager=None,
    memory_system=None,
    conversation_core=None,
    message_manager=None
) -> GatewayIntegration:
    """初始化网关（全局单例）"""
    global _gateway_integration
    
    if _gateway_integration is None:
        _gateway_integration = GatewayIntegration(config_path)
        _gateway_integration.inject_dependencies(
            agent_manager, 
            memory_system, 
            conversation_core,
            message_manager
        )
        await _gateway_integration.initialize()
    
    return _gateway_integration


def get_gateway_integration() -> Optional[GatewayIntegration]:
    """获取网关实例"""
    return _gateway_integration
