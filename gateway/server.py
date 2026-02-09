"""
网关服务器 - WebSocket服务器核心
"""
import asyncio
import time
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from loguru import logger

from .protocol import (
    RequestMessage, ResponseMessage, EventMessage,
    RequestType, EventType, ConnectParams,
    GatewayProtocol, MessageType,
    SendMessageParams, AgentCallParams, MemoryQueryParams,
    HealthPayload, StatusPayload, AgentResponsePayload
)
from .connection import ConnectionManager, Connection
from .events import EventEmitter
from .tool_service import ToolService, ToolInvocationContext
from .memory_service import MemoryService
from .conversation_service import ConversationService
from .config_service import ConfigService


class GatewayServer:
    """网关服务器

    设计对齐 moltbot：Gateway 本身只是一个协议 + 事件总线层，
    具体能力（Agent、记忆、电脑控制、会话管理等）通过依赖注入提供，
    而不是在这里直接 import 其他子系统。
    """
    
    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        connection_manager: Optional[ConnectionManager] = None,
    ):
        # 事件总线 & 连接管理作为可注入依赖，便于测试和扩展
        self.event_emitter = event_emitter or EventEmitter()
        self.connection_manager = connection_manager or ConnectionManager(self.event_emitter)
        
        # 请求处理器注册表
        self._handlers: Dict[RequestType, Callable] = {}
        self._register_default_handlers()
        
        # 幂等性缓存
        self._idempotency_cache: Dict[str, ResponseMessage] = {}
        self._idempotency_ttl = 300  # 5分钟
        
        # 服务器状态
        self.started_at = None
        self.is_running = False
        
        # 通道管理器（通过 GatewayIntegration 注入）
        self.channels: Dict[str, Any] = {}
        
        # Agent / 会话管理器等运行时依赖，由上层注入
        self.agent_manager = None
        self.message_manager = None

        # 电脑控制服务，由 GatewayIntegration 注入（实现 execute_computer_action / get_computer_status）
        self.computer_service = None

        # 四个一级服务：工具、记忆、对话、配置（都通过事件总线通信）
        # 这些服务会在 GatewayIntegration 中初始化并注入依赖
        self.tool_service: Optional[ToolService] = None
        self.memory_service: Optional[MemoryService] = None
        self.conversation_service: Optional[ConversationService] = None
        self.config_service: Optional[ConfigService] = None
        
        # 向后兼容：保留旧属性名（指向新服务）
        self.memory_system = None  # 将指向 memory_service.memory_adapter
        self.conversation_core = None  # 将指向 conversation_service.conversation_core
        
    def _register_default_handlers(self):
        """注册默认请求处理器"""
        self._handlers[RequestType.CONNECT] = self._handle_connect
        self._handlers[RequestType.HEALTH] = self._handle_health
        self._handlers[RequestType.STATUS] = self._handle_status
        self._handlers[RequestType.SEND] = self._handle_send
        self._handlers[RequestType.AGENT] = self._handle_agent
        self._handlers[RequestType.CHANNELS_STATUS] = self._handle_channels_status
        self._handlers[RequestType.SYSTEM_INFO] = self._handle_system_info
        
        # 记忆系统
        self._handlers[RequestType.MEMORY_QUERY] = self._handle_memory_query
        self._handlers[RequestType.MEMORY_CLUSTER] = self._handle_memory_cluster
        self._handlers[RequestType.MEMORY_SUMMARIZE] = self._handle_memory_summarize
        self._handlers[RequestType.MEMORY_GRAPH] = self._handle_memory_graph
        self._handlers[RequestType.MEMORY_DECAY] = self._handle_memory_decay
        self._handlers[RequestType.MEMORY_CLEANUP] = self._handle_memory_cleanup
        
        # 会话管理
        self._handlers[RequestType.SESSIONS_LIST] = self._handle_sessions_list
        self._handlers[RequestType.SESSION_DETAIL] = self._handle_session_detail
        self._handlers[RequestType.SESSION_DELETE] = self._handle_session_delete
        
        # 追问系统
        self._handlers[RequestType.FOLLOWUP] = self._handle_followup
        
        # 工具系统
        self._handlers[RequestType.TOOLS_LIST] = self._handle_tools_list
        self._handlers[RequestType.TOOL_CALL] = self._handle_tool_call
        
        # 配置管理
        self._handlers[RequestType.CONFIG_GET] = self._handle_config_get
        self._handlers[RequestType.CONFIG_RELOAD] = self._handle_config_reload
        self._handlers[RequestType.CONFIG_UPDATE] = self._handle_config_update
        self._handlers[RequestType.CONFIG_RESET] = self._handle_config_reset
        self._handlers[RequestType.CONFIG_SWITCH_MODEL] = self._handle_config_switch_model
        self._handlers[RequestType.CONFIG_DIAGNOSE] = self._handle_config_diagnose
        
        # 电脑控制
        self._handlers[RequestType.COMPUTER_BROWSER] = self._handle_computer_control
        self._handlers[RequestType.COMPUTER_SCREEN] = self._handle_computer_control
        self._handlers[RequestType.COMPUTER_FILESYSTEM] = self._handle_computer_control
        self._handlers[RequestType.COMPUTER_PROCESS] = self._handle_computer_control
        self._handlers[RequestType.COMPUTER_STATUS] = self._handle_computer_status
    
    def register_handler(self, request_type: RequestType, handler: Callable):
        """注册自定义请求处理器"""
        self._handlers[request_type] = handler
        logger.info(f"Registered handler for: {request_type}")
    
    async def start(self):
        """启动网关服务器"""
        self.started_at = datetime.now()
        self.is_running = True
        
        # 启动后台任务
        asyncio.create_task(self._heartbeat_task())
        asyncio.create_task(self._cleanup_task())
        
        logger.info("Gateway Server started")
        await self.event_emitter.emit(EventType.HEALTH_UPDATE, {
            "status": "healthy",
            "message": "Gateway started"
        })
    
    async def _handle_computer_control(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理电脑控制请求"""
        try:
            # 提取控制器类型
            capability_map = {
                RequestType.COMPUTER_BROWSER: 'browser',
                RequestType.COMPUTER_SCREEN: 'screen',
                RequestType.COMPUTER_FILESYSTEM: 'filesystem',
                RequestType.COMPUTER_PROCESS: 'process'
            }
            
            capability = capability_map.get(request.method)
            if not capability:
                return GatewayProtocol.create_response(
                    request.id,
                    False,
                    error="Unknown computer control request"
                )
            
            action = request.params.get('action')
            params = request.params.get('params', {})
            
            if not action:
                return GatewayProtocol.create_response(
                    request.id,
                    False,
                    error="Missing 'action' parameter"
                )
            
            # 通过依赖注入的电脑控制服务执行（避免 Gateway 反向依赖 gateway_integration 模块）
            integration = getattr(self, "computer_service", None)
            
            if not integration:
                return GatewayProtocol.create_response(
                    request.id,
                    False,
                    error="Computer control service not initialized"
                )
            
            result = await integration.execute_computer_action(capability, action, params)
            
            return GatewayProtocol.create_response(
                request.id,
                result.success,
                payload={
                    "result": result.result,
                    "screenshot": result.screenshot,
                    "metadata": result.metadata
                } if result.success else None,
                error=result.error
            )
            
        except Exception as e:
            logger.error(f"Error in computer control: {e}")
            return GatewayProtocol.create_response(
                request.id,
                False,
                error=str(e)
            )
    
    async def _handle_computer_status(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """获取电脑控制器状态"""
        try:
            integration = getattr(self, "computer_service", None)
            
            if not integration:
                return GatewayProtocol.create_response(
                    request.id,
                    False,
                    error="Computer control service not initialized"
                )
            
            status = integration.get_computer_status()
            
            return GatewayProtocol.create_response(
                request.id,
                True,
                payload={"controllers": status}
            )
            
        except Exception as e:
            logger.error(f"Error getting computer status: {e}")
            return GatewayProtocol.create_response(
                request.id,
                False,
                error=str(e)
            )
    
    async def stop(self):
        """停止网关服务器"""
        self.is_running = False
        logger.info("Gateway Server stopped")
    
    async def handle_connection(self, websocket, connection: Connection):
        """处理WebSocket连接"""
        connection_id = connection.connection_id
        
        try:
            while self.is_running:
                # 接收消息
                data = await websocket.receive_text()
                
                try:
                    # 解析消息
                    message = GatewayProtocol.parse_message(data)
                    
                    if isinstance(message, RequestMessage):
                        await self._handle_request(connection, message)
                    else:
                        logger.warning(f"Unexpected message type from {connection_id}: {message.type}")
                        
                except Exception as e:
                    logger.error(f"Error parsing message from {connection_id}: {e}")
                    await connection.send_response(
                        "unknown",
                        False,
                        error=f"Invalid message format: {str(e)}"
                    )
                    
        except Exception as e:
            logger.error(f"Connection error {connection_id}: {e}")
        finally:
            await self.connection_manager.disconnect(connection_id)
    
    async def _handle_request(self, connection: Connection, request: RequestMessage):
        """处理请求"""
        # 检查幂等性
        if request.idempotency_key:
            cached = self._idempotency_cache.get(request.idempotency_key)
            if cached:
                logger.debug(f"Returning cached response for idempotency_key: {request.idempotency_key}")
                await connection.send_message(cached)
                return
        
        # 更新心跳
        await self.connection_manager.heartbeat(connection.connection_id)
        
        # 获取处理器
        handler = self._handlers.get(request.method)
        if not handler:
            await connection.send_response(
                request.id,
                False,
                error=f"Unknown request method: {request.method}"
            )
            return
        
        try:
            # 调用处理器
            response = await handler(connection, request)
            
            # 缓存幂等性响应
            if request.idempotency_key and response.ok:
                self._idempotency_cache[request.idempotency_key] = response
            
            await connection.send_message(response)
            
        except Exception as e:
            logger.error(f"Error handling request {request.method}: {e}")
            await connection.send_response(
                request.id,
                False,
                error=f"Internal error: {str(e)}"
            )
    
    # ============ 请求处理器 ============
    
    async def _handle_connect(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理连接请求"""
        try:
            connect_params = ConnectParams(**request.params)
            
            # 更新连接身份
            connection.identity = connect_params.identity
            connection.is_authenticated = True  # TODO: 实现真正的认证
            
            # 发送欢迎载荷
            payload = {
                "status": "connected",
                "connection_id": connection.connection_id,
                "server_version": "1.0.0",
                "protocol_version": "1.0",
                "capabilities": ["agent", "memory", "channels", "tools"],
                "health": await self._get_health_info(),
            }
            
            return GatewayProtocol.create_response(request.id, True, payload)
            
        except Exception as e:
            return GatewayProtocol.create_response(
                request.id, False, error=f"Connect failed: {str(e)}"
            )
    
    async def _handle_health(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理健康检查"""
        health_info = await self._get_health_info()
        return GatewayProtocol.create_response(request.id, True, health_info)
    
    async def _handle_status(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理状态查询"""
        status_info = {
            "gateway_status": "running" if self.is_running else "stopped",
            "uptime": (datetime.now() - self.started_at).total_seconds() if self.started_at else 0,
            "connections": self.connection_manager.get_active_count(),
            "channels": {name: {"status": "active"} for name in self.channels.keys()},
            "agents": {},  # TODO: 从 agent_manager 获取
            "nodes": {},
        }
        return GatewayProtocol.create_response(request.id, True, status_info)
    
    async def _handle_send(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理发送消息"""
        try:
            params = SendMessageParams(**request.params)
            
            # TODO: 路由到对应通道
            channel = self.channels.get(params.channel)
            if not channel:
                return GatewayProtocol.create_response(
                    request.id, False, error=f"Channel not found: {params.channel}"
                )
            
            # 发送消息（待实现）
            result = {
                "status": "sent",
                "channel": params.channel,
                "target": params.target,
                "message_id": f"msg_{int(time.time() * 1000)}"
            }
            
            return GatewayProtocol.create_response(request.id, True, result)
            
        except Exception as e:
            return GatewayProtocol.create_response(
                request.id, False, error=f"Send failed: {str(e)}"
            )
    
    async def _handle_agent(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理Agent调用"""
        try:
            params = AgentCallParams(**request.params)
            
            if not self.agent_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Agent manager not initialized"
                )
            
            # 生成运行ID
            run_id = f"run_{int(time.time() * 1000)}"
            
            # 发送接受响应
            accept_payload = {
                "run_id": run_id,
                "status": "accepted",
            }
            
            # 异步执行Agent调用
            if params.stream:
                asyncio.create_task(
                    self._execute_agent_stream(connection, run_id, params)
                )
            else:
                asyncio.create_task(
                    self._execute_agent(connection, run_id, params)
                )
            
            return GatewayProtocol.create_response(request.id, True, accept_payload)
            
        except Exception as e:
            return GatewayProtocol.create_response(
                request.id, False, error=f"Agent call failed: {str(e)}"
            )
    
    async def _handle_channels_status(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理通道状态查询"""
        channels_info = {
            name: {
                "status": "active",
                "type": getattr(channel, 'channel_type', 'unknown')
            }
            for name, channel in self.channels.items()
        }
        return GatewayProtocol.create_response(request.id, True, {"channels": channels_info})
    
    async def _handle_system_info(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理系统信息查询"""
        system_info = {
            "version": "1.0.0",
            "uptime": (datetime.now() - self.started_at).total_seconds() if self.started_at else 0,
            "connections": self.connection_manager.get_active_count(),
            "channels": list(self.channels.keys()),
            "features": ["agent", "memory", "mcp", "channels", "nodes"],
        }
        return GatewayProtocol.create_response(request.id, True, system_info)
    
    async def _handle_memory_query(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理记忆查询"""
        try:
            params = MemoryQueryParams(**request.params)
            
            if not self.memory_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory service not initialized"
                )
            
            # 通过 MemoryService 获取记忆上下文
            context = await self.memory_service.get_context(
                query=params.query,
                session_id=params.session_id or "default",
                user_id=params.filters.get("user_id") if params.filters else None
            )
            
            results = {
                "query": params.query,
                "context": context,
                "total": len(context) if context else 0,
            }
            
            return GatewayProtocol.create_response(request.id, True, results)
            
        except Exception as e:
            return GatewayProtocol.create_response(
                request.id, False, error=f"Memory query failed: {str(e)}"
            )
    
    async def _handle_tools_list(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理工具列表查询

        对外协议保持不变，但内部通过 ToolService 统一实现：
        - 优先列出 MCP / Agent handoff 服务
        - 同时包含本地注册工具（若有）
        """
        try:
            if not self.tool_service:
                self.tool_service = ToolService(self.event_emitter)

            tools_payload = await self.tool_service.list_tools()
            
            return GatewayProtocol.create_response(request.id, True, tools_payload)
        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_tool_call(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理工具调用

        对外协议保持不变：
        - params.tool_name: 工具/服务名（必填）
        - params.params:    具体参数（包含 service_name / tool_name / 业务参数等）

        内部通过 ToolService 进行调度，并在事件总线上发出 TOOL_CALL_* 事件。
        """
        try:
            if not self.tool_service:
                self.tool_service = ToolService(self.event_emitter)

            tool_name = request.params.get("tool_name")
            tool_params = request.params.get("params", {})
            
            if not tool_name:
                return GatewayProtocol.create_response(
                    request.id,
                    False,
                    error="Missing 'tool_name' in params",
                )

            ctx = ToolInvocationContext(
                session_id=tool_params.get("session_id"),
                user_id=tool_params.get("user_id"),
                source="gateway",
                metadata={
                    "connection_id": connection.connection_id,
                    "request_method": request.method,
                },
            )

            result = await self.tool_service.call_tool(
                tool_name=tool_name,
                params=tool_params,
                ctx=ctx,
                request_id=request.id,
                connection_id=connection.connection_id,
            )
            
            return GatewayProtocol.create_response(
                request.id,
                True,
                {
                "tool": tool_name,
                    "result": result,
                },
            )
        except Exception as e:
            logger.error(f"Error calling tool: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    # ============ 记忆系统处理器 ============
    
    async def _handle_memory_cluster(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理记忆聚类"""
        try:
            from .protocol import MemoryClusterParams
            
            params = MemoryClusterParams(**request.params)
            
            if not self.memory_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory service not initialized"
                )
            
            if not self.memory_service.is_enabled():
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory system not enabled"
                )
            
            result = await self.memory_service.cluster_entities(params.session_id)
            
            return GatewayProtocol.create_response(request.id, True, {
                "session_id": params.session_id,
                **result
            })
        except Exception as e:
            logger.error(f"Error clustering memory: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_memory_summarize(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理记忆摘要"""
        try:
            from .protocol import MemorySummarizeParams
            
            params = MemorySummarizeParams(**request.params)
            
            if not self.memory_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory service not initialized"
                )
            
            if not self.memory_service.is_enabled():
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory system not enabled"
                )
            
            result = await self.memory_service.summarize_session(
                params.session_id,
                incremental=params.incremental
            )
            
            return GatewayProtocol.create_response(request.id, True, result)
        except Exception as e:
            logger.error(f"Error summarizing memory: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_memory_graph(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理记忆图查询"""
        try:
            from .protocol import SessionParams
            
            params = SessionParams(**request.params)
            
            if not self.memory_service or not self.memory_service.is_enabled():
                return GatewayProtocol.create_response(request.id, True, {
                    "nodes": [],
                    "edges": [],
                    "stats": {"total_nodes": 0, "total_edges": 0}
                })
            
            memory_adapter = self.memory_service.memory_adapter
            if not memory_adapter or not memory_adapter.hot_layer:
                return GatewayProtocol.create_response(request.id, True, {
                    "nodes": [],
                    "edges": [],
                    "stats": {"total_nodes": 0, "total_edges": 0}
                })
            
            connector = memory_adapter.hot_layer.connector
            
            # 查询节点
            nodes_query = """
            MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(n)
            RETURN n.id as id, labels(n)[0] as type, n.content as content,
                   n.layer as layer, n.importance as importance
            """
            
            # 查询边
            edges_query = """
            MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(n1)
            MATCH (n1)-[r]->(n2)
            RETURN n1.id as source, n2.id as target, type(r) as type
            """
            
            session_param = {"session_id": f"session_{params.session_id}"}
            nodes_raw = connector.query(nodes_query, session_param)
            edges_raw = connector.query(edges_query, session_param)
            
            nodes = [{"id": n.get("id"), "type": n.get("type"), "content": n.get("content")} 
                    for n in nodes_raw]
            edges = [{"source": e.get("source"), "target": e.get("target"), "type": e.get("type")} 
                    for e in edges_raw]
            
            return GatewayProtocol.create_response(request.id, True, {
                "nodes": nodes,
                "edges": edges,
                "stats": {"total_nodes": len(nodes), "total_edges": len(edges)}
            })
        except Exception as e:
            logger.error(f"Error getting memory graph: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_memory_decay(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理记忆衰减"""
        try:
            from .protocol import SessionParams
            
            params = SessionParams(**request.params)
            
            if not self.memory_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory service not initialized"
                )
            
            if not self.memory_service.is_enabled():
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory system not enabled"
                )
            
            result = await self.memory_service.apply_decay(params.session_id)
            
            return GatewayProtocol.create_response(request.id, True, result)
        except Exception as e:
            logger.error(f"Error applying memory decay: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_memory_cleanup(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理记忆清理"""
        try:
            from .protocol import SessionParams
            
            params = SessionParams(**request.params)
            
            if not self.memory_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory service not initialized"
                )
            
            if not self.memory_service.is_enabled():
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory system not enabled"
                )
            
            result = await self.memory_service.cleanup_forgotten(params.session_id)
            
            return GatewayProtocol.create_response(request.id, True, result)
        except Exception as e:
            logger.error(f"Error cleaning up memory: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    # ============ 会话管理处理器 ============
    
    async def _handle_sessions_list(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理会话列表查询"""
        try:
            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )
            
            sessions_info = self.message_manager.get_all_sessions_info()
            sessions = []
            for sid, info in sessions_info.items():
                if info:
                    sessions.append(info)
            sessions.sort(key=lambda x: x.get("last_activity", 0), reverse=True)
            
            return GatewayProtocol.create_response(request.id, True, {
                "sessions": sessions,
                "total": len(sessions)
            })
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_session_detail(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理会话详情查询"""
        try:
            from .protocol import SessionParams
            
            params = SessionParams(**request.params)

            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )

            session_info = self.message_manager.get_session(params.session_id)
            
            if not session_info:
                return GatewayProtocol.create_response(
                    request.id, False, error="Session not found"
                )
            
            messages = self.message_manager.get_messages(params.session_id)
            
            return GatewayProtocol.create_response(request.id, True, {
                "session_id": params.session_id,
                "session_info": session_info,
                "messages": messages
            })
        except Exception as e:
            logger.error(f"Error getting session detail: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_session_delete(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理会话删除"""
        try:
            from .protocol import SessionParams
            
            params = SessionParams(**request.params)

            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )

            deleted = self.message_manager.delete_session(params.session_id)
            
            return GatewayProtocol.create_response(request.id, True, {
                "session_id": params.session_id,
                "status": "deleted" if deleted else "not_found"
            })
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    # ============ 追问系统处理器 ============
    
    async def _handle_followup(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理追问请求"""
        try:
            from .protocol import FollowupParams
            
            params = FollowupParams(**request.params)
            
            # 追问模板
            templates = {
                "why": "为什么说「{text}」？请用100字以内简短解释推理依据和前提。",
                "risk": "「{text}」有什么潜在的坑或代价？请用100字以内诚实说明。",
                "alternative": "除了「{text}」，还有什么替代方案？请用100字以内列举2-3个方案并简要对比。",
            }
            
            if params.query_type == "custom" and params.custom_query:
                user_query = f"{params.custom_query}\n\n相关内容：「{params.selected_text}」"
            else:
                user_query = templates.get(params.query_type, templates["why"]).format(
                    text=params.selected_text[:100]
                )
            
            # 获取最近消息
            messages = []
            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )

            recent_messages = self.message_manager.get_recent_messages(params.session_id, count=6)
            if recent_messages:
                messages = [{"role": msg["role"], "content": msg["content"]} 
                           for msg in recent_messages]
            
            messages.append({"role": "user", "content": user_query})
            
            # 调用LLM（通过 ConversationService）
            if not self.conversation_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Conversation service not initialized"
                )

            response = await self.conversation_service.call_llm(messages)
            result = response.get("content", "")

            return GatewayProtocol.create_response(
                request.id,
                True,
                {
                    "query": user_query,
                    "response": result,
                },
            )
        except Exception as e:
            logger.error(f"Error handling followup: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    # ============ 配置管理处理器 ============
    
    async def _handle_config_get(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理配置获取"""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            # 获取用户ID（如果有）
            user_id = request.params.get("user_id")
            
            # 获取合并后的配置
            config_data = self.config_service.get_merged_config(user_id)
            
            return GatewayProtocol.create_response(request.id, True, config_data)
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_config_reload(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理配置重载"""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )

            # 重新加载默认配置
            result = await self.config_service.reload_default_config()

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
    
    async def _handle_config_update(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理配置更新"""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            user_id = request.params.get("user_id")
            if not user_id:
                return GatewayProtocol.create_response(
                    request.id, False, error="user_id is required"
                )
            
            config_updates = request.params.get("config", {})
            if not config_updates:
                return GatewayProtocol.create_response(
                    request.id, False, error="config updates are required"
                )
            
            result = await self.config_service.update_user_config(user_id, config_updates)
            
            return GatewayProtocol.create_response(
                request.id,
                result["success"],
                payload=result if result["success"] else None,
                error=result.get("message") if not result["success"] else None
            )
        except Exception as e:
            logger.error(f"Error updating config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_config_reset(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理配置重置"""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            user_id = request.params.get("user_id")
            if not user_id:
                return GatewayProtocol.create_response(
                    request.id, False, error="user_id is required"
                )
            
            reset_to_default = request.params.get("reset_to_default", True)
            
            result = await self.config_service.reset_user_config(user_id, reset_to_default)
            
            return GatewayProtocol.create_response(
                request.id,
                result["success"],
                payload=result if result["success"] else None,
                error=result.get("message") if not result["success"] else None
            )
        except Exception as e:
            logger.error(f"Error resetting config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_config_switch_model(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理模型切换"""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            user_id = request.params.get("user_id")
            if not user_id:
                return GatewayProtocol.create_response(
                    request.id, False, error="user_id is required"
                )
            
            model = request.params.get("model")
            if not model:
                return GatewayProtocol.create_response(
                    request.id, False, error="model is required"
                )
            
            api_key = request.params.get("api_key")
            base_url = request.params.get("base_url")
            
            result = await self.config_service.switch_model(user_id, model, api_key, base_url)
            
            return GatewayProtocol.create_response(
                request.id,
                result["success"],
                payload=result if result["success"] else None,
                error=result.get("message") if not result["success"] else None
            )
        except Exception as e:
            logger.error(f"Error switching model: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_config_diagnose(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """处理配置诊断"""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            user_id = request.params.get("user_id")
            
            result = self.config_service.diagnose_config(user_id)
            
            return GatewayProtocol.create_response(request.id, True, result)
        except Exception as e:
            logger.error(f"Error diagnosing config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    # ============ 辅助方法 ============
    
    async def _get_health_info(self) -> Dict[str, Any]:
        """获取健康信息"""
        return {
            "status": "healthy" if self.is_running else "unhealthy",
            "uptime": (datetime.now() - self.started_at).total_seconds() if self.started_at else 0,
            "active_connections": self.connection_manager.get_active_count(),
            "channels": {
                name: {"status": "active"}
                for name in self.channels.keys()
            },
        }
    
    async def _execute_agent(self, connection: Connection, run_id: str, params: AgentCallParams):
        """执行Agent调用（非流式）"""
        try:
            # 发送开始事件
            await connection.send_event(EventType.AGENT_START, {"run_id": run_id})
            
            # 调用Agent
            result = await self.agent_manager.call_agent(
                params.agent_name,
                params.prompt,
                params.session_id
            )
            
            # 发送完成事件
            if result.get("status") == "success":
                await connection.send_event(EventType.AGENT_COMPLETE, {
                    "run_id": run_id,
                    "result": result.get("result"),
                    "status": "completed"
                })
            else:
                await connection.send_event(EventType.AGENT_ERROR, {
                    "run_id": run_id,
                    "error": result.get("error"),
                    "status": "error"
                })
                
        except Exception as e:
            logger.error(f"Error executing agent {run_id}: {e}")
            await connection.send_event(EventType.AGENT_ERROR, {
                "run_id": run_id,
                "error": str(e),
                "status": "error"
            })
    
    async def _execute_agent_stream(self, connection: Connection, run_id: str, params: AgentCallParams):
        """执行Agent调用（流式）"""
        # TODO: 实现流式调用
        await self._execute_agent(connection, run_id, params)
    
    async def _heartbeat_task(self):
        """心跳任务"""
        while self.is_running:
            await asyncio.sleep(30)  # 每30秒发送一次心跳
            await self.connection_manager.broadcast(
                EventType.HEARTBEAT,
                {"timestamp": datetime.now().isoformat()}
            )
    
    async def _cleanup_task(self):
        """清理任务"""
        while self.is_running:
            await asyncio.sleep(60)  # 每分钟清理一次
            
            # 清理过期的幂等性缓存
            now = time.time()
            expired_keys = [
                key for key, response in self._idempotency_cache.items()
                if (now - response.timestamp.timestamp()) > self._idempotency_ttl
            ]
            for key in expired_keys:
                del self._idempotency_cache[key]
            
            # 清理过期连接
            await self.connection_manager.cleanup_stale_connections()
