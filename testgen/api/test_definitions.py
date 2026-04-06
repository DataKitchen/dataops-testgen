"""API v1 — test definition export and import."""

from fastapi import APIRouter, Depends, HTTPException, Query

from testgen.api import test_definition_service
from testgen.api.deps import db_session, resolve_test_suite
from testgen.api.schemas import (
    ErrorDetail,
    ErrorResponse,
    ExportDocument,
    ImportMode,
    ImportRequest,
    ImportResponse,
    ImportStrictError,
    Origin,
)
from testgen.common.models.test_suite import TestSuite

_error_responses = {
    404: {"model": ErrorResponse, "description": "Not found"},
}

router = APIRouter(
    prefix="/api/v1",
    tags=["test-definitions"],
    dependencies=[Depends(db_session)],
    responses=_error_responses,
)


@router.get(
    "/test-suites/{test_suite_id}/test-definition-export",
    response_model=ExportDocument,
    response_model_exclude_defaults=True,
)
def export_test_definitions(
    test_suite: TestSuite = resolve_test_suite("view"),  # noqa: B008
    origin: Origin = Query(default=Origin.both),  # noqa: B008
    table_name: str | None = Query(default=None),
    test_type: str | None = Query(default=None),
) -> ExportDocument:
    """Export test definitions from a test suite as a portable JSON document."""
    return test_definition_service.export_definitions(test_suite, origin, table_name, test_type)


@router.post(
    "/test-suites/{test_suite_id}/test-definition-import",
    response_model=ImportResponse,
    responses={
        400: {"model": ImportStrictError, "description": "Invalid request or strict validation failed"},
    },
)
def import_test_definitions(
    body: ImportRequest,
    test_suite: TestSuite = resolve_test_suite("edit"),  # noqa: B008
) -> ImportResponse:
    """Import test definitions into a test suite from a portable JSON document."""
    result = test_definition_service.import_definitions(test_suite, body.config, body.payload)

    if body.config.mode == ImportMode.apply_strict and result.summary.skipped > 0:
        raise HTTPException(
            status_code=400,
            detail=ImportStrictError(
                errors=[ErrorDetail(
                    code="strict_validation_failed",
                    detail=f"{result.summary.skipped} test definition(s) would be skipped",
                )],
                import_result=result,
            ).model_dump(mode="json"),
        )

    return result
