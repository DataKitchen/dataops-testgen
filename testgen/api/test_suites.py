"""API v1 — test suites."""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query

from testgen.api.deps import api_errors, db_session, resolve_project_code, resolve_table_group, resolve_test_suite
from testgen.api.enums import DEFAULT_SEVERITY_FROM_DB, DEFAULT_SEVERITY_TO_DB, DefaultSeverity
from testgen.api.schemas import (
    ErrorResponse,
    ResultCounts,
    TestSuiteCreate,
    TestSuiteItem,
    TestSuiteLatestRun,
    TestSuiteListResponse,
    TestSuiteResponse,
)
from testgen.common.database.test_suite_service import validate_test_suite_fields
from testgen.common.enums import SuiteType
from testgen.common.models import get_current_session
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import SuiteSeverity, TestSuite, TestSuiteListItem

_error_responses = {404: {"model": ErrorResponse, "description": "Not found"}}

router = APIRouter(tags=["Test Suites"], dependencies=[Depends(db_session, scope="function")], responses=_error_responses)


@router.get(
    "/projects/{project_code}/test-suites",
    response_model=TestSuiteListResponse,
    summary="List test suites",
)
def list_test_suites(
    project_code: str = resolve_project_code("view"),
    table_group_id: UUID | None = Query(default=None, description="Only test suites in this table group."),  # noqa: B008
    test_suite_name: str | None = Query(default=None, description="Only test suites with exactly this name."),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Test suites in a project, each with its test count and last completed run.

    Test suite names are not unique, so ``test_suite_name`` can match more than one
    suite. Filter by it before creating a suite to avoid making a second one.
    """
    clauses = []
    if table_group_id is not None:
        clauses.append(TestSuite.table_groups_id == table_group_id)
    if test_suite_name is not None:
        clauses.append(TestSuite.test_suite == test_suite_name)
    rows, total = TestSuite.list_for_project(project_code, *clauses, page=page, limit=limit)
    return TestSuiteListResponse(items=[_to_item(row) for row in rows], page=page, limit=limit, total=total)


@router.get(
    "/test-suites/{test_suite_id}",
    response_model=TestSuiteResponse,
    summary="Read a test suite",
)
def get_test_suite(test_suite: TestSuite = resolve_test_suite("view")):  # noqa: B008
    """A test suite's configuration: its default severity, scoring and Observability
    settings, the generation sets test generation uses, and whether it is its table
    group's default suite.
    """
    return _to_response(test_suite, TableGroup.get(test_suite.table_groups_id))


@router.post(
    "/table-groups/{table_group_id}/test-suites",
    response_model=TestSuiteResponse,
    status_code=201,
    summary="Create a test suite",
    responses={400: {"model": ErrorResponse, "description": "One entry per field that failed validation"}},
)
def create_test_suite(
    table_group: TableGroup = resolve_table_group("edit"),  # noqa: B008
    body: TestSuiteCreate = Body(...),  # noqa: B008
) -> TestSuiteResponse:
    """Create a test suite in a table group. It belongs to the table group's project and connection.

    Test suite names are not unique: repeating a create makes a second suite with the
    same name. ``set_as_default`` makes the table group's first profiling run generate
    tests into the new suite.
    """
    test_suite = TestSuite(
        project_code=table_group.project_code,
        connection_id=table_group.connection_id,
        table_groups_id=table_group.id,
        test_suite=body.test_suite_name.strip(),
        test_suite_description=body.description,
        severity=DEFAULT_SEVERITY_TO_DB[DefaultSeverity(body.default_severity)] if body.default_severity else None,
        dq_score_exclude=body.exclude_from_quality_score,
        deactivate_invalid_tests=body.deactivate_invalid_tests,
        export_to_observability=body.export_to_observability,
        component_key=body.component_key,
        component_type=body.component_type,
        component_name=body.component_name,
        generation_sets=body.generation_sets,
        suite_type=SuiteType.REGULAR,
    )
    if errors := validate_test_suite_fields(test_suite):
        raise api_errors(400, "invalid_test_suite", errors)

    test_suite.save()
    if body.set_as_default:
        table_group.default_test_suite_id = test_suite.id
        table_group.save()

    get_current_session().refresh(test_suite)
    return _to_response(test_suite, table_group)


def _to_response(test_suite: TestSuite, table_group: TableGroup | None) -> TestSuiteResponse:
    return TestSuiteResponse(
        test_suite_id=test_suite.id,
        test_suite_name=test_suite.test_suite,
        project_code=test_suite.project_code,
        connection_id=test_suite.connection_id,
        table_group_id=test_suite.table_groups_id,
        description=test_suite.test_suite_description,
        default_severity=DEFAULT_SEVERITY_FROM_DB[SuiteSeverity(test_suite.severity)] if test_suite.severity else None,
        exclude_from_quality_score=bool(test_suite.dq_score_exclude),
        deactivate_invalid_tests=bool(test_suite.deactivate_invalid_tests),
        export_to_observability=bool(test_suite.export_to_observability),
        component_key=test_suite.component_key,
        component_type=test_suite.component_type,
        component_name=test_suite.component_name,
        generation_sets=test_suite.generation_sets or [],
        is_default=table_group is not None and table_group.default_test_suite_id == test_suite.id,
    )


def _to_item(row: TestSuiteListItem) -> TestSuiteItem:
    latest_run = None
    if row.latest_run_id is not None:
        latest_run = TestSuiteLatestRun(
            job_execution_id=row.latest_run_id,
            started_at=row.latest_run_started_at,
            test_count=row.latest_run_test_count,
            result_counts=ResultCounts(
                passed=row.latest_run_passed_count or 0,
                failed=row.latest_run_failed_count or 0,
                warning=row.latest_run_warning_count or 0,
                error=row.latest_run_error_count or 0,
                log=row.latest_run_log_count or 0,
                dismissed=row.latest_run_dismissed_count or 0,
            ),
        )
    return TestSuiteItem(
        test_suite_id=row.id,
        test_suite_name=row.test_suite,
        project_code=row.project_code,
        connection_id=row.connection_id,
        table_group_id=row.table_groups_id,
        table_group_name=row.table_groups_name,
        description=row.test_suite_description,
        test_count=row.test_count,
        latest_run=latest_run,
    )
