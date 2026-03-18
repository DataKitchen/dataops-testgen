"""TestGen API endpoints — health, ping."""

from fastapi import APIRouter, Depends

from testgen.api.deps import db_session, get_authorized_user
from testgen.common import version_service

router = APIRouter(prefix="/api/v1", tags=["api"], dependencies=[Depends(db_session)])

_require_user = Depends(get_authorized_user)


@router.get("/health")
def health():
    version = version_service.get_version()
    return {
        "status": "ok",
        "edition": version.edition,
        "version": version.current,
    }


@router.get("/ping")
def ping(user=_require_user):
    return {
        "status": "ok",
        "username": user.username,
    }
