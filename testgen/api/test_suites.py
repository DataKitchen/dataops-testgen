"""API v1 — test suites."""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.exc import IntegrityError

from testgen.api.deps import (
    LimitQuery,
    PageQuery,
    api_error,
    api_errors,
    db_session,
    resolve_project_code,
    resolve_table_group,
    resolve_test_suite,
)
from testgen.api.enums import (
    DEFAULT_SEVERITY_FROM_DB,
    DEFAULT_SEVERITY_TO_DB,
    RESULT_STATUS_FROM_DB,
    DefaultSeverity,
    TestSuiteType,
)
from testgen.api.schemas import (
    ContractActiveVersion,
    ContractCustomServer,
    ContractGeneration,
    ContractRun,
    ContractStatusResponse,
    ContractVerification,
    ErrorResponse,
    ResultCounts,
    TestSuiteCreate,
    TestSuiteCreatedResponse,
    TestSuiteItem,
    TestSuiteLatestRun,
    TestSuiteListResponse,
    TestSuiteResponse,
)
from testgen.commands.test_generation import resolve_generation_profile_run
from testgen.common import contract_creation, contract_document, contract_service
from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.audit.test_suites import record_contract_created
from testgen.common.database.test_suite_service import is_duplicate_name_error, validate_test_suite_fields
from testgen.common.enums import TEST_SUITE_TYPES, SuiteType
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.suite_version import ContractState, SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRunSummary, run_verdict
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
    suite_type: TestSuiteType | None = Query(  # noqa: B008
        default=None,
        description="Only test suites of this type: `regular` or `contract`. Omit to list both.",
    ),
    page: int = PageQuery,
    limit: int = LimitQuery,
):
    """Test suites in a project, contracts included, each with its test count and last completed run.

    `test_suite_name` matches the name exactly; filter by it to check whether a name is free
    before creating a suite. A contract also carries the numbers of its active version and
    its draft.
    """
    clauses = []
    if table_group_id is not None:
        clauses.append(TestSuite.table_groups_id == table_group_id)
    if test_suite_name is not None:
        clauses.append(TestSuite.test_suite == test_suite_name)
    suite_types = (SuiteType(suite_type),) if suite_type else TEST_SUITE_TYPES
    rows, total = TestSuite.list_for_project(project_code, *clauses, page=page, limit=limit, suite_types=suite_types)
    contract_ids = [row.id for row in rows if row.suite_type == SuiteType.CONTRACT]
    states = SuiteVersion.states_for(contract_ids) if contract_ids else {}
    return TestSuiteListResponse(
        items=[_to_item(row, states.get(row.id)) for row in rows], page=page, limit=limit, total=total
    )


@router.get(
    "/test-suites/{test_suite_id}",
    response_model=TestSuiteResponse,
    summary="Read a test suite",
)
def get_test_suite(test_suite: TestSuite = resolve_test_suite("view", TEST_SUITE_TYPES)):  # noqa: B008
    """A test suite's configuration: its default severity, scoring and Observability
    settings, the generation sets test generation uses, and whether it is its table
    group's default suite.

    A contract also carries its active version, its draft, and the latest run that verified
    the active version.
    """
    return _to_response(test_suite, TableGroup.get(test_suite.table_groups_id))


@router.post(
    "/table-groups/{table_group_id}/test-suites",
    response_model=TestSuiteCreatedResponse,
    status_code=201,
    summary="Create a test suite",
    responses={
        400: {"model": ErrorResponse, "description": "One entry per field that failed validation"},
        409: {"model": ErrorResponse, "description": "A test suite or contract with this name already exists in the project"},
    },
)
def create_test_suite(
    table_group: TableGroup = resolve_table_group("edit"),  # noqa: B008
    body: TestSuiteCreate = Body(...),  # noqa: B008
) -> TestSuiteCreatedResponse:
    """Create a test suite, regular or contract, in a table group. It belongs to the table group's
    project and connection.

    A name another test suite or contract in the project holds is rejected. `set_as_default`
    makes the table group's first profiling run generate tests into the new suite.

    A contract is created with its first draft. Given `table_names`, it declares those tables
    and is generated for them before the response returns: its metadata from the data catalog,
    a schema conformance test per table, and, for the tables profiling has results for, their
    tests. When generation fails, the contract is still created; submit test generation for it
    to retry.
    """
    is_contract = body.suite_type == TestSuiteType.contract  # type: ignore[attr-defined]
    _check_contract_fields(body, table_group, is_contract)
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
        suite_type=SuiteType(body.suite_type),
    )
    if errors := validate_test_suite_fields(test_suite):
        raise api_errors(400, "invalid_test_suite", errors)

    try:
        if is_contract:
            return _create_contract(test_suite, table_group, body.table_names)
        test_suite.save()
    except IntegrityError as err:
        if is_duplicate_name_error(err):
            raise api_error(
                409,
                "duplicate_test_suite_name",
                "A test suite or contract with this name already exists in the project.",
            ) from err
        raise
    record(AuditAction.TEST_SUITE_CREATED, test_suite)
    if body.set_as_default:
        table_group.default_test_suite_id = test_suite.id
        table_group.save()

    get_current_session().refresh(test_suite)
    return TestSuiteCreatedResponse(**_to_response(test_suite, table_group).model_dump())


def _check_contract_fields(body: TestSuiteCreate, table_group: TableGroup, is_contract: bool) -> None:
    """Refuse the fields that apply only to one suite type, before anything is written."""
    if not is_contract:
        if body.table_names:
            raise api_error(400, "table_names_not_allowed", "table_names applies to contracts only.")
        return
    if body.set_as_default:
        raise api_error(400, "set_as_default_not_allowed", "set_as_default applies to regular test suites only.")
    if body.table_names:
        catalog_tables = set(contract_document.catalog_table_names(table_group.id))
        if unknown := [name for name in body.table_names if name not in catalog_tables]:
            raise api_error(
                400,
                "unknown_tables",
                f"Table group {table_group.table_groups_name} has no tables named {', '.join(unknown)}.",
            )


def _create_contract(
    test_suite: TestSuite, table_group: TableGroup, table_names: list[str] | None
) -> TestSuiteCreatedResponse:
    # create_contract commits before generating, so a generation failure keeps the contract; do not wrap it
    # in a rollback.
    created = contract_creation.create_contract(
        test_suite, table_group, Connection.get(table_group.connection_id), table_names
    )
    record_contract_created(created.suite)
    get_current_session().refresh(test_suite)
    generation = None
    if created.generation is not None:
        generation = ContractGeneration(
            profiled=resolve_generation_profile_run(table_group) is not None,
            tables_declared=created.generation.tables_declared,
            tables_not_in_catalog=created.generation.tables_not_in_catalog,
            tables_not_profiled=created.generation.tables_not_profiled,
            quality_test_count=created.generation.term_count,
        )
    custom_server = None
    if (reason := created.custom_server_reason) is not None:
        custom_server = ContractCustomServer(
            server_type=reason.server_type.value if reason.server_type else None,
            missing_fields=list(reason.missing_fields),
        )
    return TestSuiteCreatedResponse(
        **_to_response(test_suite, table_group).model_dump(),
        generation=generation,
        generation_failed=created.generation_failed,
        custom_server=custom_server,
    )


def _to_response(test_suite: TestSuite, table_group: TableGroup | None) -> TestSuiteResponse:
    return TestSuiteResponse(
        test_suite_id=test_suite.id,
        test_suite_name=test_suite.test_suite,
        suite_type=TestSuiteType(test_suite.suite_type),
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
        contract=_contract_status(test_suite) if test_suite.suite_type == SuiteType.CONTRACT else None,
    )


def _contract_status(test_suite: TestSuite) -> ContractStatusResponse:
    status = contract_service.contract_status(test_suite)
    return ContractStatusResponse(
        active_version=ContractActiveVersion(
            number=status.active.version, label=status.active.label, frozen_at=status.active.frozen_at
        ) if status.active else None,
        draft_version=status.draft.version if status.draft else None,
        tests_counted_from=status.counted_from.version if status.counted_from else None,
        latest_verification=_verification(status.latest_verification),
        incomplete_run=ContractRun(
            job_execution_id=status.incomplete_run.job_execution_id, status=status.incomplete_run.status
        ) if status.incomplete_run else None,
        verification_unavailable=status.unavailable,
    )


def _verification(run: TestRunSummary | None) -> ContractVerification | None:
    if run is None:
        return None
    return ContractVerification(
        job_execution_id=run.job_execution_id,
        result=RESULT_STATUS_FROM_DB[run_verdict(run)],
        started_at=run.started_at,
        test_count=run.test_ct,
        result_counts=ResultCounts(
            passed=run.passed_ct or 0,
            failed=run.failed_ct or 0,
            warning=run.warning_ct or 0,
            error=run.error_ct or 0,
            log=run.log_ct or 0,
            dismissed=run.dismissed_ct or 0,
        ),
    )


def _to_item(row: TestSuiteListItem, state: ContractState | None) -> TestSuiteItem:
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
        suite_type=TestSuiteType(row.suite_type),
        test_count=row.test_count,
        active_version=state.active.version if state and state.active else None,
        draft_version=state.draft.version if state and state.draft else None,
        latest_run=latest_run,
    )
