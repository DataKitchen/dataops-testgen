from fastapi import APIRouter

from testgen.api.app import router as _app_router
from testgen.api.jobs import router as _jobs_router
from testgen.api.monitors import router as _monitors_router
from testgen.api.runs import router as _runs_router
from testgen.api.test_definitions import router as _test_definitions_router

router = APIRouter(prefix="/api/v1")
router.include_router(_app_router)
router.include_router(_jobs_router)
router.include_router(_monitors_router)
router.include_router(_runs_router)
router.include_router(_test_definitions_router)
