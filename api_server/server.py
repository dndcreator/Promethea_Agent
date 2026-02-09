from fastapi import FastAPI, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from .chat_router import router as chat_router
from .routes.auth import router as auth_router
import sys
import os
from typing import List, Dict
import json
import asyncio
from contextlib import asynccontextmanager
from pydantic import BaseModel
import traceback
from config import config
from agentkit.mcp.mcpregistry import MCP_REGISTRY
from loguru import logger
from datetime import datetime

# Removed sys.path hack

class ConnectionManager:

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_user_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        # 创建列表副本进行遍历，避免在迭代中修改列表导致的问题
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                # 如果发送失败（连接已断开），安全移除
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

manager = ConnectionManager()
gateway_integration = None  # 网关集成实例
Promethea_agent = None

class SystemInfoResponse(BaseModel):
    version: str
    status: str
    available_services: List[str]
    api_key_configured: bool

@asynccontextmanager
async def lifespan(app: FastAPI):
    global Promethea_agent, gateway_integration
    try:
        # 1. 首先加载插件系统（确保服务注册表可用）
        logger.info("[INFO] 正在加载插件系统...")
        try:
            from core.plugins.loader import load_promethea_plugins, PluginLoadOptions
            from pathlib import Path
            
            # 读取配置以确定 memory 插件是否启用
            mem_enabled = True
            try:
                from config import config
                mem_enabled = config.memory.enabled
            except Exception:
                pass
            
            plugins_config = {
                "plugins": {
                    "memory": {"enabled": mem_enabled, "config": {}}
                }
            }
            
            load_promethea_plugins(
                PluginLoadOptions(
                    workspace_dir=str(Path(__file__).resolve().parents[1]),
                    extensions_dir="extensions",
                    config=plugins_config,
                    cache=True,
                    mode="full",
                    allow=None,
                )
            )
            logger.info("[SUCCESS] 插件系统加载完成")
        except Exception as e:
            logger.warning(f"[WARNING] 插件系统加载失败: {e}")
            logger.info("[INFO] 继续启动，但插件功能可能不可用")
            traceback.print_exc()
        
        # 2. 初始化普罗米娅AI助手（此时插件系统已加载，服务可通过注册表获取）
        logger.info("[INFO] 正在初始化普罗米娅AI助手...")
        from conversation_core import PrometheaConversation
        Promethea_agent = PrometheaConversation()
        logger.info("[SUCCESS] 普罗米娅AI助手初始化完成")
        
        # 3. 初始化 MCP 系统
        logger.info("[INFO] 正在初始化 MCP 系统...")
        try:
            from agentkit.mcp.mcpregistry import initialize_mcp_registry, ensure_builtin_service
            registered_services = initialize_mcp_registry('agentkit')
            if not registered_services:
                # 无外部服务时注册内置MVP服务
                builtin = ensure_builtin_service()
                registered_services = builtin
            logger.info(f"[SUCCESS] MCP 系统初始化完成，注册了 {len(registered_services)} 个服务: {registered_services}")
        except Exception as e:
            logger.warning(f"[WARNING] MCP 系统初始化失败: {e}")
            logger.info("[INFO] 继续启动，但 MCP 功能可能不可用")
        
        # 4. 初始化网关系统（此时插件系统已加载）
        logger.info("[INFO] 正在初始化网关系统...")
        try:
            from gateway_integration import initialize_gateway
            from agentkit.mcp.agent_manager import get_agent_manager
            from api_server.message_manager import message_manager
            
            agent_manager = get_agent_manager()
            gateway_integration = await initialize_gateway(
                config_path="gateway_config.json",
                agent_manager=agent_manager,
                conversation_core=Promethea_agent,
                message_manager=message_manager
            )
            logger.info("[SUCCESS] 网关系统初始化完成")
        except Exception as e:
            logger.warning(f"[WARNING] 网关系统初始化失败: {e}")
            logger.info("[INFO] 继续启动，但网关功能可能不可用")
            traceback.print_exc()
        
        yield
    except Exception as e:
        logger.error(f"[ERROR] 普罗米娅AI助手初始化失败: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        logger.info("[INFO] 正在清理资源...")
        
        # 清理网关
        if gateway_integration:
            try:
                await gateway_integration.shutdown()
            except Exception as e:
                logger.warning(f"[WARNING] 清理网关资源时出错: {e}")
        
        # 清理MCP
        if Promethea_agent and hasattr(Promethea_agent, "mcp"):
            try:
                await Promethea_agent.mcp.cleanup()
            except Exception as e:
                logger.warning(f"[WARNING] 清理MCP资源时出错: {e}")

    

app = FastAPI(
    title="普罗米娅AI助手 API", 
    description="智能对话助手API服务",
    version="1.0.0",
    lifespan=lifespan
)

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UI_dir = os.path.join(os.path.dirname(__file__), "..", "UI")
app.mount("/UI", StaticFiles(directory = UI_dir, html=True), name="UI")



@app.websocket("/ws/mcplog")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await manager.send_user_message(
            json.dumps({
                "type": "connection_check",
                "message": "WebSocket连接成功"
            }, ensure_ascii=False),
            websocket
        )
        while True:
            try:
                data = await websocket.receive_text()
                await manager.send_user_message(
                    json.dumps({
                        "type": "dokidoki",
                        "message": "收到心跳"
                    }, ensure_ascii=False),
                    websocket
                )
            except WebSocketDisconnect:
                manager.disconnect(websocket)
                break
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        manager.disconnect(websocket)

# 网关WebSocket端点
@app.websocket("/gateway/ws")
async def gateway_websocket_endpoint(websocket: WebSocket):
    """网关协议WebSocket端点"""
    if not gateway_integration:
        await websocket.close(code=1011, reason="Gateway not initialized")
        return
    
    try:
        gateway_server = gateway_integration.get_gateway_server()
        
        # 接受连接（先不验证，等待connect消息）
        connection = await gateway_server.connection_manager.accept(websocket, None)
        
        # 处理连接
        await gateway_server.handle_connection(websocket, connection)
        
    except Exception as e:
        logger.error(f"Gateway WebSocket error: {e}")
        try:
            await websocket.close()
        except:
            pass

# 注册路由
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(auth_router, prefix="/api", tags=["auth"])

@app.get("/", response_model = Dict[str, str])
async def root():
    return {
        "message": "普罗米娅AI助手 API 服务正在运行",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "websocket": "/ws/mcplog"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "agent_ready": Promethea_agent is not None,
        "timestamp": str(asyncio.get_event_loop().time())
    }

@app.get("/system/info", response_model=SystemInfoResponse)
async def get_system_info():
    if not Promethea_agent:
        raise HTTPException(status_code=503, detail="普罗米娅AI助手未初始化")

    return SystemInfoResponse(
        version = "1.0.0",
        status = "running",
        available_services = list(MCP_REGISTRY.keys()),
        api_key_configured = bool(config.api.api_key and config.api.api_key != "placeholder-key-not-set")        
    )

@app.get("/gateway/status")
async def get_gateway_status():
    """获取网关状态"""
    if not gateway_integration:
        return {"status": "disabled", "message": "Gateway not initialized"}
    
    gateway_server = gateway_integration.get_gateway_server()
    channel_registry = gateway_integration.get_channel_registry()
    
    return {
        "status": "running" if gateway_server.is_running else "stopped",
        "uptime": (datetime.now() - gateway_server.started_at).total_seconds() if gateway_server.started_at else 0,
        "connections": gateway_server.connection_manager.get_active_count(),
        "channels": channel_registry.get_status_all() if channel_registry else {},
        "websocket_endpoint": "/gateway/ws"
    }
