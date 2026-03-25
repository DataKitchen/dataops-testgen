"""TestGen API endpoints — health."""

from fastapi import APIRouter, Depends

from testgen.api.deps import db_session
from testgen.common import version_service

router = APIRouter(prefix="/api/v1", tags=["api"], dependencies=[Depends(db_session)])


@router.get("/health")
def health():
    version = version_service.get_version()
    return {
        "status": "ok",
        "edition": version.edition,
        "version": version.current,
    }
