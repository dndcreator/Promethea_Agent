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
from .routes.automation import router as automation_router
from .routes.skills import router as skills_router
from .routes.voice import router as voice_router
from .routes.ops import router as ops_router
from .routes.workflow import router as workflow_router
from .routes.security import router as security_router

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
router.include_router(automation_router)
router.include_router(skills_router)
router.include_router(voice_router)
router.include_router(ops_router)
router.include_router(workflow_router)
router.include_router(security_router)




