"""API v1 — test definition export and import."""

from fastapi import APIRouter, Depends, HTTPException, Query

from testgen.api.deps import api_error, db_session, resolve_test_suite
from testgen.api.schemas import (
    ErrorDetail,
    ErrorResponse,
    ImportRequest,
    ImportStrictError,
)
from testgen.common.models.test_suite import TestSuite
from testgen.common.test_definition_export_import_service import (
    ExportDocument,
    ImportResponse,
    ImportStrictViolation,
    InvalidImportPayload,
    Origin,
    export_definitions,
    import_definitions,
)

_error_responses = {
    404: {"model": ErrorResponse, "description": "Not found"},
}

router = APIRouter(
    tags=["Test Definitions"],
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
    return export_definitions(test_suite, origin, table_name, test_type)


@router.post(
    "/test-suites/{test_suite_id}/test-definition-import",
    response_model=ImportResponse,
    responses={
        400: {
            "model": ImportStrictError | ErrorResponse,
            "description": "Strict validation failed (includes the projected import result) or invalid payload",
        },
    },
)
def import_test_definitions(
    body: ImportRequest,
    test_suite: TestSuite = resolve_test_suite("edit"),  # noqa: B008
) -> ImportResponse:
    """Import test definitions into a test suite from a portable JSON document."""
    try:
        return import_definitions(test_suite, body.config, body.payload)
    except InvalidImportPayload as err:
        raise api_error(400, err.code, str(err)) from err
    except ImportStrictViolation as err:
        raise HTTPException(
            status_code=400,
            detail=ImportStrictError(
                errors=[ErrorDetail(code="strict_validation_failed", detail=str(err))],
                import_result=err.result,
            ).model_dump(mode="json"),
        ) from err
