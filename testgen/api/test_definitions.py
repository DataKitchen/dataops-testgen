"""API v1 — test definition export and import."""

from collections.abc import Iterable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from testgen.api.deps import (
    CONTRACT_VERSION_ERRORS,
    api_error,
    contract_version_error,
    db_session,
    resolve_test_suite,
)
from testgen.api.schemas import (
    ErrorDetail,
    ErrorResponse,
    ImportRequest,
    ImportStrictError,
    ImportStrictErrorBody,
)
from testgen.common import contract_service
from testgen.common.enums import TEST_SUITE_TYPES
from testgen.common.models.suite_version import (
    FrozenVersionError,
    RemovedInDraftError,
    SuiteVersion,
    UnmatchedInDraftError,
    VersionState,
    format_version,
    version_state,
)
from testgen.common.models.test_suite import TestSuite
from testgen.common.test_definition_export_import_service import (
    ExportDocument,
    ImportResponse,
    ImportStrictViolation,
    ImportTargetMissing,
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
    dependencies=[Depends(db_session, scope="function")],
    responses=_error_responses,
)


@router.get(
    "/test-suites/{test_suite_id}/test-definition-export",
    summary="Export test definitions",
    response_model=ExportDocument,
    response_model_exclude_defaults=True,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "`version` given for a suite that is not a contract, or for a version the contract does "
            "not hold",
        },
    },
)
def export_test_definitions(
    test_suite: TestSuite = resolve_test_suite("view", TEST_SUITE_TYPES),  # noqa: B008
    origin: Origin = Query(  # noqa: B008
        default=Origin.both,
        description="Only definitions of this origin: `auto` (created by test generation), `manual` (created by "
        "hand), or `both` (the default).",
    ),
    table_name: str | None = Query(
        default=None, description="Only definitions for this table, matched exactly, including case."
    ),
    test_type: str | None = Query(
        default=None, description="Only definitions of this test type, given as its code, e.g. `Dupe_Rows`."
    ),
    version: int | None = Query(
        default=None,
        ge=1,
        description="Contracts only. The number of the contract version to export. Omit to export the draft where "
        "one exists, otherwise the active version.",
    ),
) -> ExportDocument:
    """A portable JSON document of a test suite's test definitions; for a contract, those of one version.

    A contract's export names the exported version in `source.contract_version`.
    """
    version_id = None
    if version is not None:
        try:
            version_id = contract_service.version_by_number(test_suite, version).id
        except CONTRACT_VERSION_ERRORS as err:
            raise contract_version_error(err) from err
    return export_definitions(test_suite, origin, table_name, test_type, version_id=version_id)


@router.post(
    "/test-suites/{test_suite_id}/test-definition-import",
    summary="Import test definitions",
    response_model=ImportResponse,
    responses={
        400: {
            "model": ImportStrictError | ErrorResponse,
            "description": "`apply_strict` would skip entries, and the body carries the import as it would have "
            "applied; or the document is invalid",
        },
        409: {
            "model": ErrorResponse,
            "description": "A matched test definition belongs to a contract version that can no longer be edited, "
            "was removed in the draft, or no longer exists",
        },
    },
)
def import_test_definitions(
    body: ImportRequest,
    test_suite: TestSuite = resolve_test_suite("edit", TEST_SUITE_TYPES),  # noqa: B008
) -> ImportResponse:
    """Writes a portable JSON document's test definitions into a test suite. A contract's import
    writes to its draft, opening one from the active version when there is none. The response names
    that version. A refusal applies nothing.
    """
    try:
        return import_definitions(test_suite, body.config, body.payload)
    except InvalidImportPayload as err:
        raise api_error(400, err.code, str(err)) from err
    except UnmatchedInDraftError as err:
        draft = SuiteVersion.get(err.draft_id)
        raise api_error(
            409,
            "test_definition_superseded",
            f"Test definitions {_ids(err.row_ids)} in {_version_label(test_suite, err.version_id)} cannot be "
            f"matched to their copies in {format_version(draft.version, VersionState.DRAFT)}, so they "
            "cannot be edited. Export the draft to find its test definitions. Nothing was applied.",
        ) from err
    except FrozenVersionError as err:
        raise api_error(
            409,
            "version_frozen",
            f"{_version_label(test_suite, err.version_id)} can no longer be edited. Nothing was applied.",
        ) from err
    except RemovedInDraftError as err:
        raise api_error(
            409,
            "test_definition_removed_in_draft",
            f"Test definitions {_ids(err.row_ids)} were removed in {_version_label(test_suite, err.version_id)}. "
            "Nothing was applied.",
        ) from err
    except ImportTargetMissing as err:
        raise api_error(
            409, "test_definition_not_found", f"Test definition {err.row_id} no longer exists. Nothing was applied."
        ) from err
    except ImportStrictViolation as err:
        raise HTTPException(
            status_code=400,
            detail=ImportStrictErrorBody(
                errors=[ErrorDetail(code="strict_validation_failed", detail=str(err))],
                import_result=err.result,
            ).model_dump(mode="json"),
        ) from err



def _version_label(test_suite: TestSuite, version_id: UUID) -> str:
    version = SuiteVersion.get(version_id)
    is_active = SuiteVersion.is_active(version.id, test_suite.id)
    return format_version(version.version, version_state(version.frozen_at, is_active))


def _ids(row_ids: Iterable[UUID]) -> str:
    return ", ".join(str(row_id) for row_id in row_ids)
