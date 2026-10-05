"""API v1 — profiling and test run schedules."""

from datetime import UTC

from fastapi import APIRouter, Body, Depends, Query
from psycopg2.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError

from testgen.api.deps import (
    api_error,
    api_errors,
    db_session,
    resolve_project_code,
    resolve_schedule,
    resolve_table_group,
    resolve_test_suite,
)
from testgen.api.enums import SCHEDULE_KIND_FROM_JOB_KEY, SCHEDULE_KIND_TO_JOB_KEY, ScheduleKind
from testgen.api.schemas import ErrorResponse, ScheduleCreate, ScheduleListResponse, ScheduleResponse
from testgen.common.cron_service import describe_cron, normalize_cron, validate_schedule
from testgen.common.enums import JobKey
from testgen.common.models import get_current_session
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

_error_responses = {404: {"model": ErrorResponse, "description": "Not found"}}
_create_responses = {
    400: {"model": ErrorResponse, "description": "Invalid cron expression or timezone, one entry per problem"},
    409: {"model": ErrorResponse, "description": "An identical schedule already exists"},
}

router = APIRouter(tags=["Schedules"], dependencies=[Depends(db_session)], responses=_error_responses)


@router.post(
    "/table-groups/{table_group_id}/profiling-schedules",
    response_model=ScheduleResponse,
    status_code=201,
    summary="Create a profiling schedule",
    responses=_create_responses,
)
def create_profiling_schedule(
    table_group: TableGroup = resolve_table_group("edit"),  # noqa: B008
    body: ScheduleCreate = Body(...),  # noqa: B008
) -> ScheduleResponse:
    """Profile a table group on a recurring schedule."""
    return _create(table_group.project_code, JobKey.run_profile, {"table_group_id": str(table_group.id)}, body)


@router.post(
    "/test-suites/{test_suite_id}/test-run-schedules",
    response_model=ScheduleResponse,
    status_code=201,
    summary="Create a test run schedule",
    responses=_create_responses,
)
def create_test_run_schedule(
    test_suite: TestSuite = resolve_test_suite("edit"),  # noqa: B008
    body: ScheduleCreate = Body(...),  # noqa: B008
) -> ScheduleResponse:
    """Run a test suite's tests on a recurring schedule."""
    return _create(test_suite.project_code, JobKey.run_tests, {"test_suite_id": str(test_suite.id)}, body)


@router.get(
    "/projects/{project_code}/schedules",
    response_model=ScheduleListResponse,
    summary="List schedules",
)
def list_schedules(
    project_code: str = resolve_project_code("view"),
    kind: ScheduleKind | None = Query(default=None, description="Only schedules of this kind."),  # noqa: B008
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """A project's profiling and test run schedules, active and paused, each with the table
    group or test suite it runs.
    """
    schedules, total = JobSchedule.list_for_project(
        project_code,
        key_filter=[SCHEDULE_KIND_TO_JOB_KEY[kind]] if kind else None,
        page=page,
        limit=limit,
    )
    return ScheduleListResponse(items=[_to_response(s) for s in schedules], page=page, limit=limit, total=total)


@router.get(
    "/schedules/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Read a schedule",
)
def get_schedule(schedule: JobSchedule = resolve_schedule("view")):  # noqa: B008
    """A profiling or test run schedule, with when it next runs."""
    return _to_response(schedule)


def _create(project_code: str, key: JobKey, kwargs: dict[str, str], body: ScheduleCreate) -> ScheduleResponse:
    if errors := validate_schedule(body.cron_expression, body.timezone):
        raise api_errors(400, "invalid_schedule", errors)

    schedule = JobSchedule(
        project_code=project_code,
        key=key,
        kwargs=kwargs,
        cron_expr=normalize_cron(body.cron_expression),
        cron_tz=body.timezone,
        active=True,
    )
    session = get_current_session()
    try:
        session.add(schedule)
        session.flush()
    except IntegrityError as err:
        # The table's only unique constraint besides the UUID key; its name differs between a
        # fresh install and an upgraded one.
        if isinstance(err.orig, UniqueViolation):
            raise api_error(
                409, "duplicate_schedule", "An identical schedule already exists for this table group or test suite."
            ) from err
        raise
    session.refresh(schedule)
    return _to_response(schedule)


def _to_response(schedule: JobSchedule) -> ScheduleResponse:
    next_run_at = None
    if schedule.active:
        next_run_at = schedule.get_sample_triggering_timestamps(1)[0].astimezone(UTC)
    return ScheduleResponse(
        schedule_id=schedule.id,
        kind=SCHEDULE_KIND_FROM_JOB_KEY[JobKey(schedule.key)],
        project_code=schedule.project_code,
        table_group_id=schedule.kwargs.get("table_group_id"),
        test_suite_id=schedule.kwargs.get("test_suite_id"),
        cron_expression=schedule.cron_expr,
        timezone=schedule.cron_tz,
        description=describe_cron(schedule.cron_expr),
        active=bool(schedule.active),
        next_run_at=next_run_at,
    )
