"""
连接管理器 - WebSocket连接管理
"""
import asyncio
from typing import Dict, Set, Optional, Any
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
import json
from loguru import logger

from .protocol import (
    DeviceIdentity, RequestMessage, ResponseMessage, EventMessage,
    MessageType, RequestType, EventType, GatewayProtocol
)
from .events import EventEmitter


class Connection:
    """单个连接"""
    
    def __init__(
        self,
        websocket: WebSocket,
        connection_id: str,
        identity: Optional[DeviceIdentity] = None
    ):
        self.websocket = websocket
        self.connection_id = connection_id
        self.identity = identity
        self.connected_at = datetime.now()
        self.last_heartbeat = datetime.now()
        self.is_authenticated = False
        self.metadata: Dict[str, Any] = {}
        
    async def send_message(self, message: Any) -> None:
        """发送消息"""
        if isinstance(message, (ResponseMessage, EventMessage)):
            data = message.model_dump_json()
        elif isinstance(message, dict):
            data = json.dumps(message, ensure_ascii=False)
        else:
            data = str(message)
        
        await self.websocket.send_text(data)
    
    async def send_response(
        self,
        request_id: str,
        ok: bool,
        payload: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> None:
        """发送响应"""
        response = GatewayProtocol.create_response(request_id, ok, payload, error)
        await self.send_message(response)
    
    async def send_event(
        self,
        event: EventType,
        payload: Dict[str, Any],
        seq: Optional[int] = None
    ) -> None:
        """发送事件"""
        event_msg = GatewayProtocol.create_event(event, payload, seq)
        await self.send_message(event_msg)


class ConnectionManager:
    """连接管理器"""
    
    def __init__(self, event_emitter: EventEmitter):
        self.connections: Dict[str, Connection] = {}
        self.device_connections: Dict[str, str] = {}  # device_id -> connection_id
        self.event_emitter = event_emitter
        self._connection_counter = 0
        self._lock = asyncio.Lock()
        
    async def accept(
        self,
        websocket: WebSocket,
        identity: Optional[DeviceIdentity] = None
    ) -> Connection:
        """接受新连接"""
        await websocket.accept()
        
        async with self._lock:
            self._connection_counter += 1
            connection_id = f"conn_{self._connection_counter}_{datetime.now().timestamp()}"
            
            connection = Connection(websocket, connection_id, identity)
            self.connections[connection_id] = connection
            
            if identity:
                self.device_connections[identity.device_id] = connection_id
            
            logger.info(f"New connection accepted: {connection_id}")
            await self.event_emitter.emit(
                EventType.CONNECTED,
                {
                    "connection_id": connection_id,
                    "device_id": identity.device_id if identity else None,
                    "device_name": identity.device_name if identity else None,
                }
            )
            
        return connection
    
    async def disconnect(self, connection_id: str) -> None:
        """断开连接"""
        async with self._lock:
            connection = self.connections.get(connection_id)
            if not connection:
                return
            
            # 移除设备映射
            if connection.identity:
                device_id = connection.identity.device_id
                if device_id in self.device_connections:
                    del self.device_connections[device_id]
            
            # 移除连接
            del self.connections[connection_id]
            
            logger.info(f"Connection disconnected: {connection_id}")
            await self.event_emitter.emit(
                EventType.DISCONNECTED,
                {"connection_id": connection_id}
            )
    
    def get_connection(self, connection_id: str) -> Optional[Connection]:
        """获取连接"""
        return self.connections.get(connection_id)
    
    def get_connection_by_device(self, device_id: str) -> Optional[Connection]:
        """通过设备ID获取连接"""
        connection_id = self.device_connections.get(device_id)
        if connection_id:
            return self.connections.get(connection_id)
        return None
    
    async def broadcast(
        self,
        event: EventType,
        payload: Dict[str, Any],
        exclude: Optional[Set[str]] = None
    ) -> None:
        """广播事件到所有连接"""
        exclude = exclude or set()
        tasks = []
        
        for conn_id, connection in self.connections.items():
            if conn_id not in exclude:
                tasks.append(connection.send_event(event, payload))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def send_to_device(
        self,
        device_id: str,
        event: EventType,
        payload: Dict[str, Any]
    ) -> bool:
        """发送事件到特定设备"""
        connection = self.get_connection_by_device(device_id)
        if connection:
            await connection.send_event(event, payload)
            return True
        return False
    
    def get_active_count(self) -> int:
        """获取活跃连接数"""
        return len(self.connections)
    
    def get_connections_info(self) -> Dict[str, Dict[str, Any]]:
        """获取所有连接信息"""
        return {
            conn_id: {
                "connection_id": conn.connection_id,
                "device_id": conn.identity.device_id if conn.identity else None,
                "device_name": conn.identity.device_name if conn.identity else None,
                "role": conn.identity.role if conn.identity else None,
                "connected_at": conn.connected_at.isoformat(),
                "is_authenticated": conn.is_authenticated,
            }
            for conn_id, conn in self.connections.items()
        }
    
    async def heartbeat(self, connection_id: str) -> None:
        """更新心跳"""
        connection = self.get_connection(connection_id)
        if connection:
            connection.last_heartbeat = datetime.now()
    
    async def cleanup_stale_connections(self, timeout_seconds: int = 300) -> None:
        """清理过期连接"""
        now = datetime.now()
        stale_connections = []
        
        for conn_id, connection in self.connections.items():
            elapsed = (now - connection.last_heartbeat).total_seconds()
            if elapsed > timeout_seconds:
                stale_connections.append(conn_id)
        
        for conn_id in stale_connections:
            logger.warning(f"Disconnecting stale connection: {conn_id}")
            await self.disconnect(conn_id)
