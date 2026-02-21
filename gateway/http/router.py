"""HTTP route registry for gateway APIs."""

from fastapi import APIRouter

from .routes.chat import router as chat_router
from .routes.status import router as status_router
from .routes.sessions import router as sessions_router
from .routes.followup import router as followup_router
from .routes.metrics_config import router as metrics_config_router
from .routes.memory import router as memory_router
from .routes.doctor import router as doctor_router
from .routes.config import router as config_router
from .routes.batch import router as batch_router

router = APIRouter()

router.include_router(chat_router)
router.include_router(status_router)
router.include_router(sessions_router)
router.include_router(followup_router)
router.include_router(metrics_config_router)
router.include_router(memory_router)
router.include_router(doctor_router)
router.include_router(config_router)
router.include_router(batch_router)

