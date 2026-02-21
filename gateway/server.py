"""
Gateway server - WebSocket-based multiplexing server.
"""
import asyncio
import os
import time
import uuid
from types import SimpleNamespace
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
from channels.base import MessageType as ChannelMessageType
from agentkit.mcp.tool_call import ToolConfirmationRequired, execute_tool_calls
from .connection import ConnectionManager, Connection
from .events import EventEmitter
from .tool_service import ToolService, ToolInvocationContext
from .memory_service import MemoryService
from .conversation_service import ConversationService
from .config_service import ConfigService
from memory.session_scope import ensure_session_owned


class GatewayServer:
    """Gateway server.
    
    Designed as the central hub between clients and the moltbot stack.
    The gateway itself is a thin orchestration + event bus layer; concrete
    capabilities (agent, memory, tools, channels, etc.) are provided via
    injected services rather than imported here directly.
    """
    
    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        connection_manager: Optional[ConnectionManager] = None,
    ):
        # Event bus & connection manager can be injected for testing/extensibility.
        self.event_emitter = event_emitter or EventEmitter()
        self.connection_manager = connection_manager or ConnectionManager(self.event_emitter)
        
        # Request handlers registry.
        self._handlers: Dict[RequestType, Callable] = {}
        self._register_default_handlers()
        
        # Idempotency cache for responses.
        self._idempotency_cache: Dict[str, ResponseMessage] = {}
        self._idempotency_ttl = 300  # 5 minutes
        
        # Server state.
        self.started_at = None
        self.is_running = False
        
        # Channel registry (registered via GatewayIntegration).
        self.channels: Dict[str, Any] = {}
        
        # Runtime dependencies, wired up by higher-level integration code.
        self.agent_manager = None
        self.message_manager = None
        self.mcp_manager = None

        # Computer-control service, registered by GatewayIntegration
        # (implements execute_computer_action / get_computer_status).
        self.computer_service = None

        # Four first-class subsystems: tools, memory, conversation, config.
        # They communicate over the event bus and are initialized via
        # GatewayIntegration.
        self.tool_service: Optional[ToolService] = None
        self.memory_service: Optional[MemoryService] = None
        self.conversation_service: Optional[ConversationService] = None
        self.config_service: Optional[ConfigService] = None
        
        # Backward-compat compatibility: keep legacy attributes pointing to
        # new services.
        self.memory_system = None  # alias to memory_service.memory_adapter
        self.conversation_core = None  # alias to conversation_service.conversation_core
        
    def _register_default_handlers(self):
        """Register default request handlers."""
        self._handlers[RequestType.CONNECT] = self._handle_connect
        self._handlers[RequestType.HEALTH] = self._handle_health
        self._handlers[RequestType.STATUS] = self._handle_status
        self._handlers[RequestType.SEND] = self._handle_send
        self._handlers[RequestType.AGENT] = self._handle_agent
        self._handlers[RequestType.CHANNELS_STATUS] = self._handle_channels_status
        self._handlers[RequestType.SYSTEM_INFO] = self._handle_system_info
        
        # Memory handlers
        self._handlers[RequestType.MEMORY_QUERY] = self._handle_memory_query
        self._handlers[RequestType.MEMORY_CLUSTER] = self._handle_memory_cluster
        self._handlers[RequestType.MEMORY_SUMMARIZE] = self._handle_memory_summarize
        self._handlers[RequestType.MEMORY_GRAPH] = self._handle_memory_graph
        self._handlers[RequestType.MEMORY_DECAY] = self._handle_memory_decay
        self._handlers[RequestType.MEMORY_CLEANUP] = self._handle_memory_cleanup
        
        # Session handlers
        self._handlers[RequestType.SESSIONS_LIST] = self._handle_sessions_list
        self._handlers[RequestType.SESSION_DETAIL] = self._handle_session_detail
        self._handlers[RequestType.SESSION_DELETE] = self._handle_session_delete
        
        # Follow-up handlers
        self._handlers[RequestType.FOLLOWUP] = self._handle_followup
        self._handlers[RequestType.CHAT] = self._handle_chat
        self._handlers[RequestType.CHAT_CONFIRM] = self._handle_chat_confirm
        self._handlers[RequestType.BATCH] = self._handle_batch
        
        # Tool handlers
        self._handlers[RequestType.TOOLS_LIST] = self._handle_tools_list
        self._handlers[RequestType.TOOL_CALL] = self._handle_tool_call
        
        # Config handlers
        self._handlers[RequestType.CONFIG_GET] = self._handle_config_get
        self._handlers[RequestType.CONFIG_RELOAD] = self._handle_config_reload
        self._handlers[RequestType.CONFIG_UPDATE] = self._handle_config_update
        self._handlers[RequestType.CONFIG_RESET] = self._handle_config_reset
        self._handlers[RequestType.CONFIG_SWITCH_MODEL] = self._handle_config_switch_model
        self._handlers[RequestType.CONFIG_DIAGNOSE] = self._handle_config_diagnose
        
        # Computer-control handlers
        self._handlers[RequestType.COMPUTER_BROWSER] = self._handle_computer_control
        self._handlers[RequestType.COMPUTER_SCREEN] = self._handle_computer_control
        self._handlers[RequestType.COMPUTER_FILESYSTEM] = self._handle_computer_control
        self._handlers[RequestType.COMPUTER_PROCESS] = self._handle_computer_control
        self._handlers[RequestType.COMPUTER_STATUS] = self._handle_computer_status
    
    def register_handler(self, request_type: RequestType, handler: Callable):
        """Register a request handler."""
        self._handlers[request_type] = handler
        logger.info(f"Registered handler for: {request_type}")

    def _validate_request_params(
        self,
        method: RequestType,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate request params with protocol-level schemas when available."""
        from .protocol import (
            FollowupParams,
            ChatParams,
            ChatConfirmParams,
            MemoryClusterParams,
            MemorySummarizeParams,
            SessionParams,
        )

        validators = {
            RequestType.SEND: SendMessageParams,
            RequestType.AGENT: AgentCallParams,
            RequestType.MEMORY_QUERY: MemoryQueryParams,
            RequestType.FOLLOWUP: FollowupParams,
            RequestType.CHAT: ChatParams,
            RequestType.CHAT_CONFIRM: ChatConfirmParams,
            RequestType.MEMORY_CLUSTER: MemoryClusterParams,
            RequestType.MEMORY_SUMMARIZE: MemorySummarizeParams,
            RequestType.SESSION_DETAIL: SessionParams,
            RequestType.SESSION_DELETE: SessionParams,
            RequestType.MEMORY_GRAPH: SessionParams,
            RequestType.MEMORY_DECAY: SessionParams,
            RequestType.MEMORY_CLEANUP: SessionParams,
        }
        model = validators.get(method)
        if not model:
            return params
        obj = model(**params)
        return obj.model_dump() if hasattr(obj, "model_dump") else obj.dict()

    async def handle_http_request(
        self,
        method: RequestType,
        params: Dict[str, Any],
        user_id: str,
        timeout_ms: Optional[int] = None,
        retries: int = 0,
    ) -> ResponseMessage:
        """
        HTTP -> gateway protocol bridge.
        Keeps HTTP and WebSocket on the same request-handler table.
        """

        class _HttpConnection:
            def __init__(self, uid: str):
                self.connection_id = f"http_{uuid.uuid4().hex}"
                self.identity = SimpleNamespace(device_id=uid)
                self.is_authenticated = True
                self.metadata: Dict[str, Any] = {"transport": "http"}

            async def send_event(self, *args, **kwargs):
                return None

            async def send_message(self, *args, **kwargs):
                return None

            async def send_response(self, *args, **kwargs):
                return None

        request_id = str(uuid.uuid4())
        req_params = dict(params or {})
        req_params.setdefault("user_id", user_id)
        await self.event_emitter.emit(
            EventType.REQUEST_RECEIVED,
            {
                "request_id": request_id,
                "transport": "http",
                "method": method.value,
                "user_id": user_id,
            },
        )

        try:
            validated = self._validate_request_params(method, req_params)
        except Exception as e:
            return GatewayProtocol.create_response(
                request_id,
                False,
                error=f"invalid request params: {e}",
            )

        request = RequestMessage(id=request_id, method=method, params=validated)
        handler = self._handlers.get(method)
        if not handler:
            response = GatewayProtocol.create_response(
                request.id,
                False,
                error=f"Unknown request method: {method}",
            )
            await self.event_emitter.emit(
                EventType.REQUEST_FAILED,
                {
                    "request_id": request_id,
                    "transport": "http",
                    "method": method.value,
                    "error": response.error,
                },
            )
            return response

        guard_error = self._service_guard_error(method)
        if guard_error:
            response = GatewayProtocol.create_response(
                request.id,
                False,
                error=guard_error,
            )
            await self.event_emitter.emit(
                EventType.REQUEST_FAILED,
                {
                    "request_id": request_id,
                    "transport": "http",
                    "method": method.value,
                    "error": response.error,
                },
            )
            return response

        connection = _HttpConnection(user_id)
        attempts = max(0, int(retries)) + 1
        timeout_s = (float(timeout_ms) / 1000.0) if timeout_ms else None
        last_error = None

        for _ in range(attempts):
            try:
                if timeout_s:
                    response = await asyncio.wait_for(handler(connection, request), timeout=timeout_s)
                else:
                    response = await handler(connection, request)
                await self.event_emitter.emit(
                    EventType.REQUEST_COMPLETED,
                    {
                        "request_id": request_id,
                        "transport": "http",
                        "method": method.value,
                        "ok": response.ok,
                    },
                )
                return response
            except asyncio.TimeoutError:
                last_error = "request timeout"
            except Exception as e:
                last_error = str(e)

        response = GatewayProtocol.create_response(
            request.id,
            False,
            error=last_error or "request failed",
        )
        await self.event_emitter.emit(
            EventType.REQUEST_FAILED,
            {
                "request_id": request_id,
                "transport": "http",
                "method": method.value,
                "error": response.error,
            },
        )
        return response

    def get_services_health(self) -> Dict[str, Any]:
        """Return service readiness/availability snapshot."""
        return {
            "tool_service": bool(self.tool_service),
            "memory_service": bool(self.memory_service and self.memory_service.is_enabled()),
            "conversation_service": bool(self.conversation_service),
            "config_service": bool(self.config_service),
            "message_manager": bool(self.message_manager),
            "agent_manager": bool(self.agent_manager),
            "mcp_manager": bool(self.mcp_manager),
        }

    def _service_guard_error(self, method: RequestType) -> Optional[str]:
        """Return a degradation error when a required service is unavailable."""
        memory_methods = {
            RequestType.MEMORY_QUERY,
            RequestType.MEMORY_CLUSTER,
            RequestType.MEMORY_SUMMARIZE,
            RequestType.MEMORY_GRAPH,
            RequestType.MEMORY_DECAY,
            RequestType.MEMORY_CLEANUP,
        }
        config_methods = {
            RequestType.CONFIG_GET,
            RequestType.CONFIG_RELOAD,
            RequestType.CONFIG_UPDATE,
            RequestType.CONFIG_RESET,
            RequestType.CONFIG_SWITCH_MODEL,
            RequestType.CONFIG_DIAGNOSE,
        }
        convo_methods = {
            RequestType.CHAT,
            RequestType.CHAT_CONFIRM,
            RequestType.FOLLOWUP,
            RequestType.SESSIONS_LIST,
            RequestType.SESSION_DETAIL,
            RequestType.SESSION_DELETE,
        }

        if method in memory_methods and (
            not self.memory_service or not self.memory_service.is_enabled()
        ):
            return "memory service unavailable (degraded)"
        if method in config_methods and not self.config_service:
            return "config service unavailable (degraded)"
        if method in convo_methods and not self.conversation_service:
            return "conversation service unavailable (degraded)"
        return None
    
    async def start(self):
        """Start the gateway server and background tasks."""
        self.started_at = datetime.now()
        self.is_running = True
        
        # Start periodic background tasks.
        asyncio.create_task(self._heartbeat_task())
        asyncio.create_task(self._cleanup_task())
        
        logger.info("Gateway Server started")
        await self.event_emitter.emit(EventType.HEALTH_UPDATE, {
            "status": "healthy",
            "message": "Gateway started"
        })
    
    async def _handle_computer_control(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle computer-control requests."""
        try:
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
            
            # Execute via injected computer_service to avoid circular imports.
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
        """Get current status of the computer-control service."""
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
        """Stop the gateway server."""
        self.is_running = False
        logger.info("Gateway Server stopped")
    
    async def handle_connection(self, websocket, connection: Connection):
        """Main loop for handling a single WebSocket connection."""
        connection_id = connection.connection_id
        
        try:
            while self.is_running:
                # Receive raw message text.
                data = await websocket.receive_text()
                
                try:
                    # Parse message into protocol object.
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
        """Handle a single request message."""
        await self.event_emitter.emit(
            EventType.REQUEST_RECEIVED,
            {
                "request_id": request.id,
                "transport": "ws",
                "method": request.method.value,
                "connection_id": connection.connection_id,
            },
        )
        # Idempotency check.
        if request.idempotency_key:
            cached = self._idempotency_cache.get(request.idempotency_key)
            if cached:
                logger.debug(f"Returning cached response for idempotency_key: {request.idempotency_key}")
                await connection.send_message(cached)
                return
        
        # Update connection heartbeat.
        await self.connection_manager.heartbeat(connection.connection_id)
        
        # Lookup handler.
        handler = self._handlers.get(request.method)
        if not handler:
            await connection.send_response(
                request.id,
                False,
                error=f"Unknown request method: {request.method}"
            )
            await self.event_emitter.emit(
                EventType.REQUEST_FAILED,
                {
                    "request_id": request.id,
                    "transport": "ws",
                    "method": request.method.value,
                    "connection_id": connection.connection_id,
                    "error": f"Unknown request method: {request.method}",
                },
            )
            return
        
        try:
            # Invoke handler.
            response = await handler(connection, request)
            
            # Cache successful idempotent responses.
            if request.idempotency_key and response.ok:
                self._idempotency_cache[request.idempotency_key] = response
            
            await connection.send_message(response)
            await self.event_emitter.emit(
                EventType.REQUEST_COMPLETED,
                {
                    "request_id": request.id,
                    "transport": "ws",
                    "method": request.method.value,
                    "connection_id": connection.connection_id,
                    "ok": response.ok,
                },
            )
            
        except Exception as e:
            logger.error(f"Error handling request {request.method}: {e}")
            await connection.send_response(
                request.id,
                False,
                error=f"Internal error: {str(e)}"
            )
            await self.event_emitter.emit(
                EventType.REQUEST_FAILED,
                {
                    "request_id": request.id,
                    "transport": "ws",
                    "method": request.method.value,
                    "connection_id": connection.connection_id,
                    "error": str(e),
                },
            )
    
    # ============ Request handlers ============
    
    async def _handle_connect(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle connect request and perform optional authentication."""
        try:
            connect_params = ConnectParams(**request.params)
            
            # Save identity and validate optional token auth.
            connection.identity = connect_params.identity
            expected_token = os.getenv("GATEWAY_AUTH_TOKEN", "").strip()
            if expected_token:
                connection.is_authenticated = (connect_params.token or "") == expected_token
                if not connection.is_authenticated:
                    return GatewayProtocol.create_response(
                        request.id, False, error="Authentication failed"
                    )
            else:
                # Local default mode: keep backward compatible behavior.
                connection.is_authenticated = True
            
            # Build connect response payload.
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
        """Handle health-check request."""
        health_info = await self._get_health_info()
        health_info["services"] = self.get_services_health()
        return GatewayProtocol.create_response(request.id, True, health_info)
    
    async def _handle_status(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle gateway status query."""
        status_info = {
            "gateway_status": "running" if self.is_running else "stopped",
            "uptime": (datetime.now() - self.started_at).total_seconds() if self.started_at else 0,
            "connections": self.connection_manager.get_active_count(),
            "channels": {name: {"status": "active"} for name in self.channels.keys()},
            "agents": self._get_agents_runtime_state(),
            "nodes": {},
        }
        if self.conversation_service and hasattr(
            self.conversation_service, "get_processing_stats"
        ):
            try:
                status_info["conversation_processing"] = (
                    self.conversation_service.get_processing_stats()
                )
            except Exception:
                pass
        return GatewayProtocol.create_response(request.id, True, status_info)

    def _get_agents_runtime_state(self) -> Dict[str, Any]:
        """Best-effort agent runtime snapshot for status APIs."""
        if not self.agent_manager:
            return {"total_loaded": 0, "items": {}}

        try:
            items: Dict[str, Any] = {}
            if hasattr(self.agent_manager, "get_available_agents"):
                for agent in self.agent_manager.get_available_agents() or []:
                    key = (
                        str(agent.get("base_name") or "").strip()
                        or str(agent.get("name") or "").strip()
                    )
                    if not key:
                        continue
                    items[key] = {
                        "name": agent.get("name"),
                        "model_id": agent.get("model_id"),
                        "description": agent.get("description"),
                        "loaded": True,
                    }
            elif hasattr(self.agent_manager, "agents"):
                for key in getattr(self.agent_manager, "agents", {}).keys():
                    items[str(key)] = {"loaded": True}

            # Attach active session counts when the manager exposes in-memory session state.
            session_map = getattr(self.agent_manager, "agent_sessions", None)
            if isinstance(session_map, dict):
                for key, payload in items.items():
                    sessions = session_map.get(key)
                    if sessions is None and payload.get("name"):
                        sessions = session_map.get(str(payload["name"]))
                    payload["active_sessions"] = len(sessions or {})

            return {"total_loaded": len(items), "items": items}
        except Exception as e:
            return {"total_loaded": 0, "items": {}, "error": str(e)}

    def _resolve_request_user_id(self, connection: Connection, request: RequestMessage) -> str:
        identity = getattr(connection, "identity", None)
        device_id = getattr(identity, "device_id", None) if identity else None
        if device_id:
            return str(device_id)
        user_id = request.params.get("user_id") if isinstance(request.params, dict) else None
        if user_id:
            return str(user_id)
        return "default_user"

    def _ensure_session_access(self, session_id: str, user_id: str) -> bool:
        if not self.message_manager:
            return False
        return self.message_manager.get_session(session_id, user_id=user_id) is not None

    async def _execute_tool_for_chat(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        session_id: Optional[str],
        user_id: Optional[str],
        request_id: Optional[str] = None,
        connection_id: Optional[str] = None,
    ) -> Any:
        agent_type = str(args.get("agentType", "mcp")).lower()
        if agent_type == "agent":
            if not self.agent_manager:
                raise RuntimeError("agent manager not initialized")
            agent_name = args.get("agent_name")
            prompt = args.get("prompt")
            if not agent_name or not prompt:
                raise ValueError("missing agent_name or prompt for agent tool call")
            result = await self.agent_manager.call_agent(agent_name, prompt, session_id)
            if result.get("status") != "success":
                raise RuntimeError(result.get("error") or "agent call failed")
            return result.get("result", "")

        if not self.tool_service:
            self.tool_service = ToolService(self.event_emitter)
        ctx = ToolInvocationContext(
            session_id=session_id,
            user_id=user_id,
            source="chat",
            metadata={"request_id": request_id, "connection_id": connection_id},
        )
        return await self.tool_service.call_tool(
            tool_name=tool_name,
            params=args,
            ctx=ctx,
            request_id=request_id,
            connection_id=connection_id,
        )
    
    async def _handle_send(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle generic channel send request."""
        try:
            params = SendMessageParams(**request.params)
            
            # Route to concrete channel implementation.
            channel = self.channels.get(params.channel)
            if not channel:
                return GatewayProtocol.create_response(
                    request.id, False, error=f"Channel not found: {params.channel}"
                )
            
            if not getattr(channel, "is_connected", False):
                return GatewayProtocol.create_response(
                    request.id, False, error=f"Channel not connected: {params.channel}"
                )

            message_type = ChannelMessageType.TEXT
            if params.message_type:
                try:
                    message_type = ChannelMessageType(params.message_type)
                except ValueError:
                    message_type = ChannelMessageType.TEXT

            metadata = params.metadata or {}
            try:
                result = await channel.send_message(
                    params.target,
                    params.content,
                    message_type,
                    **metadata,
                )
            except TypeError:
                # Legacy channel signature without receiver_id.
                result = await channel.send_message(
                    params.content,
                    message_type,
                    **metadata,
                )
            
            payload = {
                "status": "sent" if result is not None else "unknown",
                "channel": params.channel,
                "target": params.target,
                "message_type": message_type.value,
                "result": result or {},
            }
            
            ok = True
            if isinstance(result, dict) and result.get("success") is False:
                ok = False
                return GatewayProtocol.create_response(
                    request.id, False, error=result.get("error", "Send failed")
                )
            
            return GatewayProtocol.create_response(request.id, ok, payload)
            
        except Exception as e:
            return GatewayProtocol.create_response(
                request.id, False, error=f"Send failed: {str(e)}"
            )
    
    async def _handle_agent(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle Agent invocation (with optional streaming)."""
        try:
            params = AgentCallParams(**request.params)
            
            if not self.agent_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Agent manager not initialized"
                )
            
            # Generate run ID.
            run_id = f"run_{int(time.time() * 1000)}"
            
            # Send accepted response.
            accept_payload = {
                "run_id": run_id,
                "status": "accepted",
            }
            
            # Run agent asynchronously (streaming or non-streaming).
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
        """Handle query for channel status."""
        channels_info = {
            name: {
                "status": "active",
                "type": getattr(channel, 'channel_type', 'unknown')
            }
            for name, channel in self.channels.items()
        }
        return GatewayProtocol.create_response(request.id, True, {"channels": channels_info})
    
    async def _handle_system_info(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle system-info query."""
        system_info = {
            "version": "1.0.0",
            "uptime": (datetime.now() - self.started_at).total_seconds() if self.started_at else 0,
            "connections": self.connection_manager.get_active_count(),
            "channels": list(self.channels.keys()),
            "features": ["agent", "memory", "mcp", "channels", "nodes"],
        }
        return GatewayProtocol.create_response(request.id, True, system_info)
    
    async def _handle_memory_query(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle memory context query."""
        try:
            params = MemoryQueryParams(**request.params)
            
            if not self.memory_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Memory service not initialized"
                )
            
            # Delegate memory query to MemoryService.
            user_id = self._resolve_request_user_id(connection, request)
            if params.session_id and not self._ensure_session_access(params.session_id, user_id):
                return GatewayProtocol.create_response(
                    request.id, False, error="Session not found"
                )
            context = await self.memory_service.get_context(
                query=params.query,
                session_id=params.session_id or "default",
                user_id=user_id,
            )
            
            results = {
                "query": params.query,
                "context": context,
                "total": len(context) if context else 0,
                "user_id": user_id,
            }
            
            return GatewayProtocol.create_response(request.id, True, results)
            
        except Exception as e:
            return GatewayProtocol.create_response(
                request.id, False, error=f"Memory query failed: {str(e)}"
            )
    
    async def _handle_tools_list(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle tool-list query.

        External protocol remains stable; internally we route via ToolService:
        - Prefer listing MCP / Agent-handoff services first
        - Also include locally registered tools when present
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
        """Handle tool-call request.

        Protocol contract:
        - params.tool_name: tool / service name (required)
        - params.params:    concrete args (may include service_name / tool_name / business args)

        Internally dispatch via ToolService and emit TOOL_CALL_* events.
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
    
    # ============ Memory-system handlers ============
    
    async def _handle_memory_cluster(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle memory clustering request."""
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
            
            user_id = self._resolve_request_user_id(connection, request)
            if not self._ensure_session_access(params.session_id, user_id):
                return GatewayProtocol.create_response(
                    request.id, False, error="Session not found"
                )

            result = await self.memory_service.cluster_entities(
                params.session_id,
                user_id=user_id,
            )
            
            return GatewayProtocol.create_response(request.id, True, {
                "session_id": params.session_id,
                "user_id": user_id,
                **result
            })
        except Exception as e:
            logger.error(f"Error clustering memory: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_memory_summarize(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle memory summarization request."""
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
            
            user_id = self._resolve_request_user_id(connection, request)
            if not self._ensure_session_access(params.session_id, user_id):
                return GatewayProtocol.create_response(
                    request.id, False, error="Session not found"
                )

            result = await self.memory_service.summarize_session(
                params.session_id,
                user_id=user_id,
                incremental=params.incremental
            )
            
            return GatewayProtocol.create_response(request.id, True, result)
        except Exception as e:
            logger.error(f"Error summarizing memory: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_memory_graph(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle query for memory graph (nodes + edges)."""
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
            user_id = self._resolve_request_user_id(connection, request)
            if not self._ensure_session_access(params.session_id, user_id):
                return GatewayProtocol.create_response(
                    request.id, False, error="Session not found"
                )
            owned, resolved_session = ensure_session_owned(
                connector,
                params.session_id,
                user_id,
            )
            if not owned:
                return GatewayProtocol.create_response(
                    request.id, False, error="Session memory not found"
                )
            
            # Query nodes in this session graph.
            nodes_query = """
            MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(n)
            RETURN n.id as id, labels(n)[0] as type, n.content as content,
                   n.layer as layer, n.importance as importance,
                   n.access_count as access_count, n.created_at as created_at
            """
            
            # Query relations in this session graph.
            edges_query = """
            MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(n1)
            MATCH (n1)-[r]->(n2)
            WHERE n2.id <> $session_id
            RETURN n1.id as source, n2.id as target, type(r) as type, r.weight as weight
            """
            
            session_param = {"session_id": f"session_{resolved_session}"}
            nodes_raw = connector.query(nodes_query, session_param)
            edges_raw = connector.query(edges_query, session_param)
            
            nodes = [
                {
                    "id": n.get("id"),
                    "type": (n.get("type", "") or "").lower(),
                    "content": n.get("content", ""),
                    "layer": n.get("layer", 0),
                    "importance": n.get("importance", 0.5),
                    "access_count": n.get("access_count", 0),
                    "created_at": n.get("created_at"),
                }
                for n in nodes_raw
            ]
            edges = [
                {
                    "source": e.get("source"),
                    "target": e.get("target"),
                    "type": e.get("type", ""),
                    "weight": e.get("weight", 1.0),
                }
                for e in edges_raw
            ]

            layer_counts = {"hot": 0, "warm": 0, "cold": 0}
            for node in nodes:
                layer = node.get("layer", 0)
                if layer == 0:
                    layer_counts["hot"] += 1
                elif layer == 1:
                    layer_counts["warm"] += 1
                elif layer == 2:
                    layer_counts["cold"] += 1
            
            return GatewayProtocol.create_response(request.id, True, {
                "session_id": params.session_id,
                "user_id": user_id,
                "nodes": nodes,
                "edges": edges,
                "stats": {
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "layers": layer_counts,
                },
            })
        except Exception as e:
            logger.error(f"Error getting memory graph: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_memory_decay(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle time-decay application over memory graph."""
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
            
            user_id = self._resolve_request_user_id(connection, request)
            if not self._ensure_session_access(params.session_id, user_id):
                return GatewayProtocol.create_response(
                    request.id, False, error="Session not found"
                )
            result = await self.memory_service.apply_decay(
                params.session_id,
                user_id=user_id,
            )
            
            return GatewayProtocol.create_response(request.id, True, result)
        except Exception as e:
            logger.error(f"Error applying memory decay: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_memory_cleanup(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle cleanup of forgotten/low-importance memory nodes."""
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
            
            user_id = self._resolve_request_user_id(connection, request)
            if not self._ensure_session_access(params.session_id, user_id):
                return GatewayProtocol.create_response(
                    request.id, False, error="Session not found"
                )
            result = await self.memory_service.cleanup_forgotten(
                params.session_id,
                user_id=user_id,
            )
            
            return GatewayProtocol.create_response(request.id, True, result)
        except Exception as e:
            logger.error(f"Error cleaning up memory: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    # ============ Conversation-management handlers ============
    
    async def _handle_sessions_list(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle query for list of sessions."""
        try:
            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )
            
            user_id = self._resolve_request_user_id(connection, request)
            sessions_info = self.message_manager.get_all_sessions_info(user_id=user_id)
            sessions = []
            for sid, info in sessions_info.items():
                if info:
                    sessions.append(info)
            sessions.sort(key=lambda x: x.get("last_activity", 0), reverse=True)
            
            return GatewayProtocol.create_response(request.id, True, {
                "sessions": sessions,
                "total": len(sessions),
                "user_id": user_id,
            })
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_session_detail(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle query for detailed session info and messages."""
        try:
            from .protocol import SessionParams
            
            params = SessionParams(**request.params)

            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )

            user_id = self._resolve_request_user_id(connection, request)
            session_info = self.message_manager.get_session(
                params.session_id, user_id=user_id
            )
            
            if not session_info:
                return GatewayProtocol.create_response(
                    request.id, False, error="Session not found"
                )
            
            messages = self.message_manager.get_messages(
                params.session_id, user_id=user_id
            )
            
            return GatewayProtocol.create_response(request.id, True, {
                "session_id": params.session_id,
                "user_id": user_id,
                "session_info": session_info,
                "messages": messages
            })
        except Exception as e:
            logger.error(f"Error getting session detail: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_session_delete(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle deletion of a session (and its messages)."""
        try:
            from .protocol import SessionParams
            
            params = SessionParams(**request.params)

            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )

            user_id = self._resolve_request_user_id(connection, request)
            deleted = self.message_manager.delete_session(
                params.session_id, user_id=user_id
            )
            
            return GatewayProtocol.create_response(request.id, True, {
                "session_id": params.session_id,
                "user_id": user_id,
                "status": "deleted" if deleted else "not_found"
            })
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    # ============ Follow-up handlers ============

    async def _handle_chat(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle one chat turn in gateway control-plane."""
        try:
            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )
            if not self.conversation_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Conversation service not initialized"
                )

            user_id = self._resolve_request_user_id(connection, request)
            user_text = (request.params.get("message") or "").strip()
            if not user_text:
                return GatewayProtocol.create_response(
                    request.id, False, error="message is required"
                )

            session_id = request.params.get("session_id")
            if session_id:
                if not self.message_manager.get_session(session_id, user_id=user_id):
                    self.message_manager.create_session(session_id=session_id, user_id=user_id)
            else:
                session_id = self.message_manager.create_session(user_id=user_id)

            turn_id = str(uuid.uuid4())
            began = self.message_manager.begin_turn(
                session_id=session_id,
                turn_id=turn_id,
                user_role="user",
                user_content=user_text,
                user_id=user_id,
            )
            if not began:
                return GatewayProtocol.create_response(
                    request.id, False, error="failed to start turn"
                )

            recent = self.message_manager.get_recent_messages(session_id, user_id=user_id)
            messages = [{"role": m["role"], "content": m["content"]} for m in recent]
            messages.append({"role": "user", "content": user_text})

            user_config = None
            if self.config_service:
                user_config = self.config_service.get_merged_config(user_id)

            tool_call_outcome = await self.conversation_service.run_chat_loop(
                messages,
                user_config,
                session_id=session_id,
                user_id=user_id,
                tool_executor=lambda name, payload: self._execute_tool_for_chat(
                    name,
                    payload,
                    session_id=session_id,
                    user_id=user_id,
                    request_id=request.id,
                    connection_id=connection.connection_id,
                ),
            )

            if tool_call_outcome.get("status") == "needs_confirmation":
                pending = dict(tool_call_outcome)
                pending["current_messages"] = messages
                pending["turn_id"] = turn_id
                self.message_manager.set_pending_confirmation(
                    session_id, pending, user_id=user_id
                )
                return GatewayProtocol.create_response(
                    request.id,
                    True,
                    {
                        "status": "needs_confirmation",
                        "session_id": session_id,
                        "tool_call_id": tool_call_outcome.get("tool_call_id"),
                        "tool_name": tool_call_outcome.get("tool_name"),
                        "args": tool_call_outcome.get("args"),
                        "response": f"Tool `{tool_call_outcome.get('tool_name')}` requires confirmation.",
                    },
                )

            final_content = tool_call_outcome.get("content", "")
            committed = self.message_manager.commit_turn(
                session_id=session_id,
                turn_id=turn_id,
                assistant_content=final_content,
                user_id=user_id,
            )
            if not committed:
                return GatewayProtocol.create_response(
                    request.id, False, error="failed to commit turn"
                )

            return GatewayProtocol.create_response(
                request.id,
                True,
                {
                    "status": "success",
                    "session_id": session_id,
                    "response": final_content,
                },
            )
        except Exception as e:
            logger.error(f"Error handling chat: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))

    async def _handle_chat_confirm(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle tool-confirmation continuation for chat turn."""
        try:
            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )
            if not self.conversation_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Conversation service not initialized"
                )

            user_id = self._resolve_request_user_id(connection, request)
            session_id = request.params.get("session_id")
            tool_call_id = request.params.get("tool_call_id")
            action = request.params.get("action")
            if not session_id or not tool_call_id:
                return GatewayProtocol.create_response(
                    request.id, False, error="session_id and tool_call_id are required"
                )

            pending = self.message_manager.get_pending_confirmation(session_id, user_id=user_id)
            if not pending:
                return GatewayProtocol.create_response(
                    request.id, False, error="no pending tool confirmation"
                )
            if pending.get("tool_call_id") != tool_call_id:
                return GatewayProtocol.create_response(
                    request.id, False, error="tool_call_id mismatch"
                )

            if action == "reject":
                turn_id = pending.get("turn_id")
                if turn_id:
                    self.message_manager.abort_turn(session_id, turn_id, user_id=user_id)
                self.message_manager.clear_pending_confirmation(session_id, user_id=user_id)
                return GatewayProtocol.create_response(
                    request.id,
                    True,
                    {"status": "rejected", "session_id": session_id, "response": "Tool execution rejected."},
                )
            if action != "approve":
                return GatewayProtocol.create_response(
                    request.id, False, error="action must be approve or reject"
                )

            current_messages = pending.get("current_messages", [])
            turn_id = pending.get("turn_id")
            tool_result_blocks = []
            try:
                all_tool_calls = pending.get("pending_tool_calls", [])
                if not all_tool_calls:
                    all_tool_calls = [
                        {
                            "name": pending.get("tool_name"),
                            "args": pending.get("args", {}),
                            "id": pending.get("tool_call_id"),
                        }
                    ]

                if not self.mcp_manager:
                    raise RuntimeError("mcp manager not initialized")
                tool_result_blocks = await execute_tool_calls(
                    all_tool_calls,
                    self.mcp_manager,
                    session_id=session_id,
                    approved_call_ids={tool_call_id},
                    tool_executor=lambda name, payload: self._execute_tool_for_chat(
                        name,
                        payload,
                        session_id=session_id,
                        user_id=user_id,
                        request_id=request.id,
                        connection_id=connection.connection_id,
                    ),
                )
            except Exception as e:
                if isinstance(e, ToolConfirmationRequired):
                    new_pending = {
                        "status": "needs_confirmation",
                        "tool_call_id": e.tool_call_id,
                        "tool_name": e.tool_name,
                        "args": e.args,
                        "current_messages": current_messages,
                        "pending_tool_calls": e.all_tool_calls,
                        "content": pending.get("content", ""),
                        "turn_id": turn_id,
                    }
                    self.message_manager.set_pending_confirmation(
                        session_id, new_pending, user_id=user_id
                    )
                    return GatewayProtocol.create_response(
                        request.id,
                        True,
                        {
                            "status": "needs_confirmation",
                            "session_id": session_id,
                            "tool_call_id": e.tool_call_id,
                            "tool_name": e.tool_name,
                            "args": e.args,
                            "response": f"Tool `{e.tool_name}` requires confirmation.",
                        },
                    )
                logger.error(f"resume tool execution failed: {e}")
                tool_result_blocks = [{"type": "text", "text": f"tool execution error: {e}"}]

            tool_result_blocks.append(
                {"type": "text", "text": "User approved tool execution. Continue based on these results."}
            )
            observation_message = {"role": "user", "content": tool_result_blocks}

            messages = list(current_messages)
            messages.append({"role": "assistant", "content": pending.get("content", "")})
            messages.append(observation_message)

            user_config = None
            if self.config_service:
                user_config = self.config_service.get_merged_config(user_id)
            self.message_manager.clear_pending_confirmation(session_id, user_id=user_id)

            tool_call_outcome = await self.conversation_service.run_chat_loop(
                messages,
                user_config,
                session_id=session_id,
                user_id=user_id,
            )

            if tool_call_outcome.get("status") == "needs_confirmation":
                next_pending = dict(tool_call_outcome)
                next_pending["current_messages"] = messages
                next_pending["turn_id"] = turn_id
                self.message_manager.set_pending_confirmation(
                    session_id, next_pending, user_id=user_id
                )
                return GatewayProtocol.create_response(
                    request.id,
                    True,
                    {
                        "status": "needs_confirmation",
                        "session_id": session_id,
                        "tool_call_id": tool_call_outcome.get("tool_call_id"),
                        "tool_name": tool_call_outcome.get("tool_name"),
                        "args": tool_call_outcome.get("args"),
                        "response": f"Tool `{tool_call_outcome.get('tool_name')}` requires confirmation.",
                    },
                )

            final_content = tool_call_outcome.get("content", "")
            if turn_id:
                committed = self.message_manager.commit_turn(
                    session_id=session_id,
                    turn_id=turn_id,
                    assistant_content=final_content,
                    user_id=user_id,
                )
                if not committed:
                    return GatewayProtocol.create_response(
                        request.id, False, error="failed to commit confirmed turn"
                    )
            else:
                self.message_manager.add_message(session_id, "assistant", final_content, user_id)

            return GatewayProtocol.create_response(
                request.id,
                True,
                {"status": "success", "session_id": session_id, "response": final_content},
            )
        except Exception as e:
            logger.error(f"Error handling chat confirm: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))

    async def _handle_followup(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle follow-up query requests."""
        try:
            from .protocol import FollowupParams

            params = FollowupParams(**request.params)
            templates = {
                "why": "Why did you say \"{text}\"? Explain the reasoning in under 100 words.",
                "risk": "What risks or trade-offs are in \"{text}\"? Keep it under 100 words.",
                "alternative": "Besides \"{text}\", list 2-3 alternatives and compare briefly in under 100 words.",
            }

            if params.query_type == "custom" and params.custom_query:
                user_query = f"{params.custom_query}\n\nRelated text: {params.selected_text}"
            else:
                user_query = templates.get(params.query_type, templates["why"]).format(
                    text=params.selected_text[:100]
                )

            if not self.message_manager:
                return GatewayProtocol.create_response(
                    request.id, False, error="Message manager not initialized"
                )

            user_id = self._resolve_request_user_id(connection, request)
            recent_messages = self.message_manager.get_recent_messages(
                params.session_id, count=6, user_id=user_id
            )
            messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in (recent_messages or [])
            ]
            messages.append({"role": "user", "content": user_query})

            if not self.conversation_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Conversation service not initialized"
                )

            response = await self.conversation_service.call_llm(
                messages,
                user_id=user_id,
            )
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

    async def _handle_batch(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle batch requests with optional timeout/retry/priority per item."""
        try:
            items = request.params.get("requests", [])
            user_id = self._resolve_request_user_id(connection, request)
            if not isinstance(items, list) or not items:
                return GatewayProtocol.create_response(
                    request.id, False, error="requests must be a non-empty list"
                )

            normalized = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized.append(
                    {
                        "method": item.get("method"),
                        "params": item.get("params", {}) or {},
                        "timeout_ms": item.get("timeout_ms"),
                        "retries": int(item.get("retries", 0) or 0),
                        "priority": int(item.get("priority", 0) or 0),
                    }
                )
            normalized.sort(key=lambda x: x["priority"], reverse=True)

            results = []
            for item in normalized:
                method_raw = item.get("method")
                try:
                    method = RequestType(method_raw)
                except Exception:
                    results.append(
                        {"method": method_raw, "ok": False, "error": f"Unknown method: {method_raw}"}
                    )
                    continue

                payload = dict(item.get("params") or {})
                payload.setdefault("user_id", user_id)
                response = await self.handle_http_request(
                    method=method,
                    params=payload,
                    user_id=user_id,
                    timeout_ms=item.get("timeout_ms"),
                    retries=item.get("retries", 0),
                )
                if response.ok:
                    results.append({"method": method.value, "ok": True, "payload": response.payload or {}})
                else:
                    results.append({"method": method.value, "ok": False, "error": response.error})

            return GatewayProtocol.create_response(request.id, True, {"results": results})
        except Exception as e:
            logger.error(f"Error handling batch: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    # ============ Config-management handlers ============
    
    async def _handle_config_get(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle configuration fetch for current user."""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            user_id = self._resolve_request_user_id(connection, request)
            config_data = self.config_service.get_merged_config(user_id)
            
            return GatewayProtocol.create_response(request.id, True, config_data)
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    async def _handle_config_reload(self, connection: Connection, request: RequestMessage) -> ResponseMessage:
        """Handle reload of default configuration."""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )

            # Reload default config from disk.
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
        """Handle user configuration update."""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            user_id = self._resolve_request_user_id(connection, request)
            
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
        """Handle user configuration reset."""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            user_id = self._resolve_request_user_id(connection, request)
            
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
        """Handle switching of underlying LLM model for current user."""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            user_id = self._resolve_request_user_id(connection, request)
            
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
        """Handle configuration diagnostics for current user."""
        try:
            if not self.config_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Config service not initialized"
                )
            
            user_id = self._resolve_request_user_id(connection, request)

            result = self.config_service.diagnose_config(user_id)
            
            return GatewayProtocol.create_response(request.id, True, result)
        except Exception as e:
            logger.error(f"Error diagnosing config: {e}")
            return GatewayProtocol.create_response(request.id, False, error=str(e))
    
    # ============ Helpers ============
    
    async def _get_health_info(self) -> Dict[str, Any]:
        """Collect current health information for the gateway."""
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
        """Execute Agent call (non-streaming)."""
        try:
            # Emit start event.
            await connection.send_event(EventType.AGENT_START, {"run_id": run_id})
            
            # Execute agent call.
            result = await self.agent_manager.call_agent(
                params.agent_name,
                params.prompt,
                params.session_id
            )
            
            # Emit completion/error events.
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
        """Execute Agent call (streaming)."""
        try:
            await connection.send_event(EventType.AGENT_START, {"run_id": run_id})

            streamed_chunks = []
            stream_started = False

            if hasattr(self.agent_manager, "call_agent_stream"):
                try:
                    async for chunk in self.agent_manager.call_agent_stream(
                        params.agent_name,
                        params.prompt,
                        params.session_id,
                    ):
                        if not chunk:
                            continue
                        stream_started = True
                        streamed_chunks.append(chunk)
                        await connection.send_event(
                            EventType.AGENT_STREAM,
                            {"run_id": run_id, "chunk": chunk, "finished": False},
                        )
                    content = "".join(streamed_chunks)
                    await connection.send_event(
                        EventType.AGENT_STREAM,
                        {"run_id": run_id, "chunk": "", "finished": True},
                    )
                    await connection.send_event(
                        EventType.AGENT_COMPLETE,
                        {"run_id": run_id, "result": content, "status": "completed"},
                    )
                    return
                except Exception as e:
                    if stream_started:
                        logger.error(f"Streaming agent {run_id} failed after partial output: {e}")
                        await connection.send_event(
                            EventType.AGENT_ERROR,
                            {"run_id": run_id, "error": str(e), "status": "error"},
                        )
                        return
                    logger.warning(f"Streaming not available, fallback to non-stream: {e}")

            result = await self.agent_manager.call_agent(
                params.agent_name,
                params.prompt,
                params.session_id,
            )

            if result.get("status") == "success":
                content = result.get("result", "") or ""
                chunk_size = 256
                for idx in range(0, len(content), chunk_size):
                    await connection.send_event(
                        EventType.AGENT_STREAM,
                        {"run_id": run_id, "chunk": content[idx:idx + chunk_size], "finished": False},
                    )
                await connection.send_event(
                    EventType.AGENT_STREAM,
                    {"run_id": run_id, "chunk": "", "finished": True},
                )
                await connection.send_event(
                    EventType.AGENT_COMPLETE,
                    {"run_id": run_id, "result": content, "status": "completed"},
                )
            else:
                await connection.send_event(
                    EventType.AGENT_ERROR,
                    {"run_id": run_id, "error": result.get("error"), "status": "error"},
                )
        except Exception as e:
            logger.error(f"Error executing agent {run_id}: {e}")
            await connection.send_event(
                EventType.AGENT_ERROR,
                {"run_id": run_id, "error": str(e), "status": "error"},
            )
    
    async def _heartbeat_task(self):
        """Periodic heartbeat broadcast task."""
        while self.is_running:
            await asyncio.sleep(30)  # broadcast every 30 seconds
            health_payload = {
                "timestamp": datetime.now().isoformat(),
                "services": self.get_services_health(),
            }
            await self.event_emitter.emit(EventType.HEALTH_UPDATE, health_payload)
            await self.connection_manager.broadcast(
                EventType.HEARTBEAT,
                health_payload,
            )
    
    async def _cleanup_task(self):
        """Periodic cleanup task (idempotency cache + stale connections)."""
        while self.is_running:
            await asyncio.sleep(60)  # run once per minute
            
            # Cleanup expired idempotency-cache entries.
            now = time.time()
            expired_keys = [
                key for key, response in self._idempotency_cache.items()
                if (now - response.timestamp.timestamp()) > self._idempotency_ttl
            ]
            for key in expired_keys:
                del self._idempotency_cache[key]
            
            # Cleanup stale websocket connections.
            await self.connection_manager.cleanup_stale_connections()

