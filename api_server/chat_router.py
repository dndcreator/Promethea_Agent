"""
路由聚合器（仅做结构重构，保证对外 API 不变）

说明：
- 原先所有端点都在这个文件里，维护成本高；
- 现在按职责拆到 `api_server/routes/*`；
- 本文件只负责把各子路由 include 回同一个 `router`，供 `api_server/server.py` 挂载。
"""

from fastapi import APIRouter

from .routes.chat import router as chat_router
from .routes.status import router as status_router
from .routes.sessions import router as sessions_router
from .routes.followup import router as followup_router
from .routes.metrics_config import router as metrics_config_router
from .routes.memory import router as memory_router
from .routes.doctor import router as doctor_router
from .routes.config import router as config_router

router = APIRouter()

# 组装顺序不影响路径（路径都不同），但这里保持“先核心后附加”的直觉顺序
router.include_router(chat_router)
router.include_router(status_router)
router.include_router(sessions_router)
router.include_router(followup_router)
router.include_router(metrics_config_router)
router.include_router(memory_router)
router.include_router(doctor_router)
router.include_router(config_router)

