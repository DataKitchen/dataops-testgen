"""MCP tools for managing recurring TestGen schedules — profiling and test-run schedules."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import select

from testgen.common.cron_service import describe_cron, get_cron_sample
from testgen.common.enums import JobKey
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRunSummary  # STATUS_LABEL is shared with ProfilingRunSummary
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    format_page_footer,
    format_page_info,
    format_run_duration,
    resolve_schedule,
    resolve_table_group,
    resolve_test_suite,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.TRIGGER


class ScheduleType(StrEnum):
    profiling_run = "profiling_run"
    test_run = "test_run"


_SCHEDULE_TYPE_TO_JOB_KEY: dict[ScheduleType, JobKey] = {
    ScheduleType.profiling_run: JobKey.run_profile,
    ScheduleType.test_run: JobKey.run_tests,
}


def _kind_display(key: str) -> str:
    """User-facing label for a schedule's job kind."""
    if key == JobKey.run_profile:
        return "Profiling Run"
    return "Test Run"

# ---------------------------------------------------------------------------
# Validation + rendering helpers
# ---------------------------------------------------------------------------


def _validate_cron(cron_expression: str, cron_tz: str) -> str:
    """Validate cron expression + timezone. Returns the human-readable description."""
    if not cron_expression:
        raise MCPUserError("`cron_expression` is required.")
    if not cron_tz:
        raise MCPUserError("`cron_tz` is required (IANA name, e.g. `UTC`).")
    sample = get_cron_sample(cron_expression, cron_tz, sample_count=1)
    if "error" in sample:
        raise MCPUserError(f"Invalid cron expression or timezone: {sample['error']}")
    return sample["readable_expr"]


def _parse_schedule_type(value: str) -> ScheduleType:
    try:
        return ScheduleType(value)
    except ValueError as err:
        valid = ", ".join(t.value for t in ScheduleType)
        raise MCPUserError(f"Invalid schedule_type `{value}`. Valid values: {valid}") from err


def _linked_kind_label(key: str) -> str:
    """Field label for the linked entity row, based on the schedule's ``key``."""
    if key == JobKey.run_profile:
        return "Table Group"
    return "Test Suite"


def _linked_entity_id(sched: JobSchedule) -> str | None:
    """Extract the linked entity UUID from ``kwargs``. ``None`` if the row is malformed."""
    if sched.key == JobKey.run_profile:
        return sched.kwargs.get("table_group_id")
    return sched.kwargs.get("test_suite_id")


def _format_linked(sched: JobSchedule, name: str | None) -> str:
    """Combined ``<Kind>: `name` (ID: `uuid`)`` line used by both detail block and list rows."""
    linked_id = _linked_entity_id(sched)
    name_part = f"`{name}`" if name else "—"
    id_part = f" (ID: `{linked_id}`)" if linked_id else ""
    return f"{name_part}{id_part}"


def _next_run(sched: JobSchedule) -> datetime | None:
    try:
        return sched.get_sample_triggering_timestamps(1)[0]
    except Exception:
        return None


def _render_schedule(
    doc: MdDoc,
    sched: JobSchedule,
    *,
    linked_name: str | None,
    include_next_runs: int = 1,
) -> None:
    doc.field("Schedule ID", sched.id, code=True)
    doc.field("Type", _kind_display(sched.key))
    doc.field(_linked_kind_label(sched.key), _format_linked(sched, linked_name))
    doc.field("Cron expression", sched.cron_expr, code=True)
    if (readable := describe_cron(sched.cron_expr)) is not None:
        doc.field("Cron description", readable)
    doc.field("Timezone", sched.cron_tz)
    doc.field("Status", "Active" if sched.active else "Paused")
    if include_next_runs > 0:
        try:
            next_times = sched.get_sample_triggering_timestamps(include_next_runs)
        except Exception:
            next_times = []
        if next_times:
            label = "Next run" if include_next_runs == 1 else "Next runs"
            doc.field(label, ", ".join(_format_dt(t) for t in next_times))


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M %Z") or value.strftime("%Y-%m-%d %H:%M")


def _resolve_linked_names(schedules: list[JobSchedule]) -> dict[tuple[str, str], str]:
    """Batch-fetch linked-entity names for a list of schedules. Avoids N+1.

    Returns a dict keyed by (kind, id) where kind ∈ {'tg', 'suite'} and id is the UUID string.
    """
    session = get_current_session()
    tg_ids: set[str] = set()
    suite_ids: set[str] = set()
    for sched in schedules:
        linked_id = _linked_entity_id(sched)
        if linked_id is None:
            continue
        if sched.key == JobKey.run_profile:
            tg_ids.add(linked_id)
        else:
            suite_ids.add(linked_id)

    names: dict[tuple[str, str], str] = {}
    if tg_ids:
        rows = session.execute(
            select(TableGroup.id, TableGroup.table_groups_name).where(TableGroup.id.in_(tg_ids))
        ).all()
        for row_id, row_name in rows:
            names[("tg", str(row_id))] = row_name
    if suite_ids:
        rows = session.execute(
            select(TestSuite.id, TestSuite.test_suite).where(TestSuite.id.in_(suite_ids))
        ).all()
        for row_id, row_name in rows:
            names[("suite", str(row_id))] = row_name
    return names


def _linked_name(sched: JobSchedule, names: dict[tuple[str, str], str]) -> str | None:
    linked_id = _linked_entity_id(sched)
    if linked_id is None:
        return None
    kind = "tg" if sched.key == JobKey.run_profile else "suite"
    return names.get((kind, linked_id))


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------


@with_database_session
@mcp_permission("edit")
def create_profiling_schedule(
    table_group_id: str,
    cron_expression: str,
    cron_tz: str = "UTC",
    active: bool = True,
) -> str:
    """Create a recurring profiling schedule for a table group.

    Args:
        table_group_id: UUID of the table group to profile, e.g. from ``get_data_inventory``.
        cron_expression: Five-field cron expression, e.g. ``0 3 * * *`` for daily at 03:00.
        cron_tz: IANA timezone name (e.g. ``America/New_York``). Defaults to ``UTC``.
        active: Whether the schedule should start active. Defaults to ``True``.
    """
    table_group = resolve_table_group(table_group_id)
    _validate_cron(cron_expression, cron_tz)
    sched = JobSchedule(
        project_code=table_group.project_code,
        key=JobKey.run_profile,
        kwargs={"table_group_id": str(table_group.id)},
        cron_expr=cron_expression,
        cron_tz=cron_tz,
        active=active,
    )
    sched.save()

    doc = MdDoc()
    doc.heading(1, f"Profiling schedule created for `{table_group.table_groups_name}`")
    _render_schedule(doc, sched, linked_name=table_group.table_groups_name)
    return doc.render()


@with_database_session
@mcp_permission("edit")
def create_test_run_schedule(
    test_suite_id: str,
    cron_expression: str,
    cron_tz: str = "UTC",
    active: bool = True,
) -> str:
    """Create a recurring test-run schedule for a test suite.

    Args:
        test_suite_id: UUID of the test suite to run, e.g. from ``list_test_suites``.
        cron_expression: Five-field cron expression, e.g. ``0 6 * * 1`` for Mondays at 06:00.
        cron_tz: IANA timezone name (e.g. ``America/New_York``). Defaults to ``UTC``.
        active: Whether the schedule should start active. Defaults to ``True``.
    """
    suite = resolve_test_suite(test_suite_id)
    _validate_cron(cron_expression, cron_tz)
    sched = JobSchedule(
        project_code=suite.project_code,
        key=JobKey.run_tests,
        kwargs={"test_suite_id": str(suite.id)},
        cron_expr=cron_expression,
        cron_tz=cron_tz,
        active=active,
    )
    sched.save()

    doc = MdDoc()
    doc.heading(1, f"Test run schedule created for `{suite.test_suite}`")
    _render_schedule(doc, sched, linked_name=suite.test_suite)
    return doc.render()


@with_database_session
@mcp_permission("edit")
def update_schedule(
    schedule_id: str,
    cron_expression: str | None = None,
    cron_tz: str | None = None,
    active: bool | None = None,
) -> str:
    """Update a schedule's cron, timezone, or active state. Atomic — no partial save.

    The job type and linked configuration are immutable — delete and recreate to change them.

    Args:
        schedule_id: UUID of the schedule, e.g. from ``list_schedules``.
        cron_expression: New cron expression. Omit to leave unchanged.
        cron_tz: New IANA timezone. Omit to leave unchanged.
        active: ``True`` to resume, ``False`` to pause. Omit to leave unchanged.
    """
    if cron_expression is None and cron_tz is None and active is None:
        raise MCPUserError("No fields supplied to update.")

    sched = resolve_schedule(schedule_id)

    new_expr = cron_expression if cron_expression is not None else sched.cron_expr
    new_tz = cron_tz if cron_tz is not None else sched.cron_tz
    if cron_expression is not None or cron_tz is not None:
        _validate_cron(new_expr, new_tz)

    changes: list[tuple[str, object, object]] = []
    if cron_expression is not None and cron_expression != sched.cron_expr:
        changes.append(("Cron expression", sched.cron_expr, cron_expression))
        sched.cron_expr = cron_expression
    if cron_tz is not None and cron_tz != sched.cron_tz:
        changes.append(("Timezone", sched.cron_tz, cron_tz))
        sched.cron_tz = cron_tz
    if active is not None and active != sched.active:
        before = "Active" if sched.active else "Paused"
        after = "Active" if active else "Paused"
        changes.append(("Status", before, after))
        sched.active = active

    sched.save()

    doc = MdDoc()
    doc.heading(1, "Schedule updated")
    doc.field("Schedule ID", sched.id, code=True)
    if not changes:
        doc.text("No fields changed — supplied values matched the current state.")
        return doc.render()
    doc.table(["Field", "Before", "After"], [list(c) for c in changes])
    return doc.render()


@with_database_session
@mcp_permission("edit")
def delete_schedule(schedule_id: str) -> str:
    """Delete a schedule. Past executions remain accessible via ``list_test_runs`` / ``list_profiling_runs``.

    Args:
        schedule_id: UUID of the schedule, e.g. from ``list_schedules``.
    """
    sched = resolve_schedule(schedule_id)
    JobSchedule.delete(sched.id)

    doc = MdDoc()
    doc.heading(1, "Schedule deleted")
    doc.field("Schedule ID", sched.id, code=True)
    return doc.render()


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


@with_database_session
@mcp_permission("view")
def list_schedules(
    project_code: str,
    schedule_type: str | None = None,
    limit: int = 20,
    page: int = 1,
) -> str:
    """List schedules for a project — profiling and test run schedules.

    Args:
        project_code: Project to scope to, e.g. from ``list_projects``.
        schedule_type: Optional filter — ``profiling_run`` or ``test_run``.
        limit: Max rows per page. Defaults to 20.
        page: 1-indexed page number. Defaults to 1.
    """
    validate_page(page)
    validate_limit(limit, 100)

    perms = get_project_permissions()
    if project_code not in perms.allowed_codes:
        raise MCPResourceNotAccessible("Project", project_code)

    key_filter: list[JobKey] | None = None
    if schedule_type is not None:
        st_enum = _parse_schedule_type(schedule_type)
        key_filter = [_SCHEDULE_TYPE_TO_JOB_KEY[st_enum]]

    schedules, total = JobSchedule.list_for_project(
        project_code,
        key_filter=key_filter,
        page=page,
        limit=limit,
    )

    doc = MdDoc()
    doc.heading(1, f"Schedules — `{project_code}`")
    info = format_page_info(total, page, limit)
    if info:
        doc.text(info)
    if not schedules:
        doc.text("_No schedules._")
        return doc.render()

    linked_names = _resolve_linked_names(schedules)
    rows: list[list[object]] = []
    for sched in schedules:
        rows.append([
            sched.id,
            _kind_display(sched.key),
            f"{_linked_kind_label(sched.key)}: {_format_linked(sched, _linked_name(sched, linked_names))}",
            sched.cron_expr,
            sched.cron_tz,
            "Active" if sched.active else "Paused",
            _format_dt(_next_run(sched)),
        ])
    doc.table(
        ["Schedule ID", "Type", "Details", "Cron", "Timezone", "Status", "Next run"],
        rows,
        code=[0, 3],
    )
    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)
    return doc.render()


@with_database_session
@mcp_permission("view")
def get_schedule(schedule_id: str) -> str:
    """Get full details for a schedule, including the last five execution attempts.

    Args:
        schedule_id: UUID of the schedule, e.g. from ``list_schedules``.
    """
    sched = resolve_schedule(schedule_id)
    linked_names = _resolve_linked_names([sched])
    linked_name = _linked_name(sched, linked_names)

    doc = MdDoc()
    doc.heading(1, "Schedule")
    _render_schedule(doc, sched, linked_name=linked_name, include_next_runs=3)

    history = get_current_session().scalars(
        select(JobExecution)
        .where(JobExecution.job_schedule_id == sched.id)
        .order_by(JobExecution.created_at.desc())
        .limit(5)
    ).all()

    doc.heading(2, "Recent runs")
    if not history:
        doc.text("_No runs yet._")
        return doc.render()

    rows: list[list[object]] = []
    for je in history:
        rows.append([
            je.id,
            TestRunSummary.STATUS_LABEL.get(je.status, je.status),
            je.started_at,
            je.completed_at,
            format_run_duration(je.started_at, je.completed_at),
        ])
    doc.table(
        ["Job ID", "Status", "Started", "Completed", "Duration"],
        rows,
        code=[0],
    )
    doc.text(
        "_Showing the 5 most recent runs._ "
        "Use `list_test_runs` or `list_profiling_runs` for full history."
    )
    return doc.render()
