from fastapi import FastAPI, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from .chat_router import router as chat_router
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
            except:
                # 如果发送失败（连接已断开），安全移除
                if connection in self.active_connections:
                self.active_connections.remove(connection)

manager = ConnectionManager()

class SystemInfoResponse(BaseModel):
    version: str
    status: str
    available_services: List[str]
    api_key_configured: bool

@asynccontextmanager
async def lifespan(app: FastAPI):
    global Promethea_agent
    try:
        print("[INFO] 正在初始化普罗米娅AI助手...")
        from conversation_core import PrometheaConversation
        Promethea_agent = PrometheaConversation()
        print("[SUCCESS] 普罗米娅AI助手初始化完成")
        
        # 初始化 MCP 系统
        print("[INFO] 正在初始化 MCP 系统...")
        try:
            from agentkit.mcp.mcpregistry import initialize_mcp_registry, ensure_builtin_service
            registered_services = initialize_mcp_registry('agentkit')
            if not registered_services:
                # 无外部服务时注册内置MVP服务
                builtin = ensure_builtin_service()
                registered_services = builtin
            print(f"[SUCCESS] MCP 系统初始化完成，注册了 {len(registered_services)} 个服务: {registered_services}")
        except Exception as e:
            print(f"[WARNING] MCP 系统初始化失败: {e}")
            print("[INFO] 继续启动，但 MCP 功能可能不可用")
        
        yield
    except Exception as e:
        print(f"[ERROR] 普罗米娅AI助手初始化失败: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("[INFO] 正在清理资源...")
        if Promethea_agent and hasattr(Promethea_agent, "mcp"):
            try:
                await Promethea_agent.mcp.cleanup()
            except Exception as e:
                print(f"[WARNING] 清理MCP资源时出错: {e}")

    

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
        print(f"WebSocket错误: {e}")
        manager.disconnect(websocket)

# 注册路由
app.include_router(chat_router, prefix="/api", tags=["chat"])

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



