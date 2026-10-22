"""TestGen API endpoints — health."""

from fastapi import APIRouter, Depends

from testgen.api.deps import db_session
from testgen.common import version_service

router = APIRouter(tags=["Health"], dependencies=[Depends(db_session, scope="function")])


@router.get("/health", summary="Check health")
def health():
    """The API's status, and the TestGen edition and version it runs. Needs no access token."""
    version = version_service.get_version()
    return {
        "status": "ok",
        "edition": version.edition,
        "version": version.current,
    }
