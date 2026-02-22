from __future__ import annotations

import asyncio
import json
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

from agentkit.mcp.mcpregistry import MCP_REGISTRY
from config import config

from gateway.http import state
from gateway.http.middleware import register_http_middlewares
from gateway.http.router import router as chat_router
from gateway.http.routes.auth import router as auth_router


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
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                if connection in self.active_connections:
                    self.active_connections.remove(connection)


manager = ConnectionManager()
gateway_integration = None
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
        logger.info("Loading plugin system...")
        try:
            from pathlib import Path

            from core.plugins.loader import PluginLoadOptions, load_promethea_plugins

            mem_enabled = True
            try:
                mem_enabled = config.memory.enabled
            except Exception:
                pass

            plugins_config = {
                "plugins": {"memory": {"enabled": mem_enabled, "config": {}}}
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
            logger.info("Plugin system loaded")
        except Exception as e:
            logger.warning(f"Plugin system load failed: {e}")
            traceback.print_exc()

        logger.info("Initializing conversation core...")
        from conversation_core import PrometheaConversation

        Promethea_agent = PrometheaConversation()
        logger.info("Conversation core initialized")

        logger.info("Initializing MCP registry...")
        try:
            from agentkit.mcp.mcpregistry import (
                ensure_builtin_service,
                initialize_mcp_registry,
            )

            registered_services = initialize_mcp_registry("agentkit")
            if not registered_services:
                registered_services = ensure_builtin_service()
            logger.info(
                f"MCP initialized with {len(registered_services)} services: {registered_services}"
            )
        except Exception as e:
            logger.warning(f"MCP initialization failed: {e}")

        logger.info("Initializing gateway integration...")
        try:
            from agentkit.mcp.agent_manager import get_agent_manager
            from gateway.http.message_manager import message_manager
            from gateway_integration import initialize_gateway

            agent_manager = get_agent_manager()
            gateway_integration = await initialize_gateway(
                config_path="gateway_config.json",
                agent_manager=agent_manager,
                conversation_core=Promethea_agent,
                message_manager=message_manager,
                mcp_manager=state.mcp_manager,
            )
            logger.info("Gateway integration initialized")
        except Exception as e:
            logger.warning(f"Gateway initialization failed: {e}")
            traceback.print_exc()

        yield
    except Exception as e:
        logger.error(f"Server startup failed: {e}")
        traceback.print_exc()
        raise
    finally:
        logger.info("Cleaning up resources...")

        if gateway_integration:
            try:
                await gateway_integration.shutdown()
            except Exception as e:
                logger.warning(f"Gateway cleanup failed: {e}")

        if Promethea_agent and hasattr(Promethea_agent, "mcp"):
            try:
                await Promethea_agent.mcp.cleanup()
            except Exception as e:
                logger.warning(f"MCP cleanup failed: {e}")


app = FastAPI(
    title="Promethea Gateway",
    description="Gateway-first backend service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error": {"code": "http_error", "message": str(exc.detail)},
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": {"code": "internal_error", "message": str(exc)},
            "request_id": getattr(request.state, "request_id", None),
        },
    )

cors_origins = os.getenv(
    "API__CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
)
allow_origins = [x.strip() for x in cors_origins.split(",") if x.strip()]
if not allow_origins:
    allow_origins = ["http://127.0.0.1:8000", "http://localhost:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_http_middlewares(app)

UI_dir = os.path.join(os.path.dirname(__file__), "..", "UI")
app.mount("/UI", StaticFiles(directory=UI_dir, html=True), name="UI")


@app.middleware("http")
async def ui_cache_control(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/UI/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.websocket("/ws/mcplog")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await manager.send_user_message(
            json.dumps(
                {"type": "connection_check", "message": "WebSocket connected"},
                ensure_ascii=False,
            ),
            websocket,
        )
        while True:
            try:
                await websocket.receive_text()
                await manager.send_user_message(
                    json.dumps(
                        {"type": "heartbeat", "message": "pong"}, ensure_ascii=False
                    ),
                    websocket,
                )
            except WebSocketDisconnect:
                manager.disconnect(websocket)
                break
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


@app.websocket("/gateway/ws")
async def gateway_websocket_endpoint(websocket: WebSocket):
    if not gateway_integration:
        await websocket.close(code=1011, reason="Gateway not initialized")
        return

    try:
        gateway_server = gateway_integration.get_gateway_server()
        connection = await gateway_server.connection_manager.accept(websocket, None)
        await gateway_server.handle_connection(websocket, connection)
    except Exception as e:
        logger.error(f"Gateway WebSocket error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(auth_router, prefix="/api", tags=["auth"])


@app.get("/", response_model=Dict[str, str])
async def root():
    return {
        "message": "Promethea Gateway is running",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "websocket": "/gateway/ws",
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "agent_ready": Promethea_agent is not None,
        "timestamp": str(asyncio.get_event_loop().time()),
    }


@app.get("/system/info", response_model=SystemInfoResponse)
async def get_system_info():
    if not Promethea_agent:
        raise HTTPException(status_code=503, detail="conversation core not initialized")

    return SystemInfoResponse(
        version="1.0.0",
        status="running",
        available_services=list(MCP_REGISTRY.keys()),
        api_key_configured=bool(
            config.api.api_key and config.api.api_key != "placeholder-key-not-set"
        ),
    )


@app.get("/gateway/status")
async def get_gateway_status():
    if not gateway_integration:
        return {"status": "disabled", "message": "Gateway not initialized"}

    gateway_server = gateway_integration.get_gateway_server()
    channel_registry = gateway_integration.get_channel_registry()

    return {
        "status": "running" if gateway_server.is_running else "stopped",
        "uptime": (
            (datetime.now() - gateway_server.started_at).total_seconds()
            if gateway_server.started_at
            else 0
        ),
        "connections": gateway_server.connection_manager.get_active_count(),
        "channels": channel_registry.get_status_all() if channel_registry else {},
        "websocket_endpoint": "/gateway/ws",
    }
