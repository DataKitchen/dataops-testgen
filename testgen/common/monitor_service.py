"""Monitor lifecycle: enable, update, and disable monitoring for a table group.

Shared by the MCP tools, the monitors dashboard, and the table-group creation
wizard so all three drive monitoring through one path. Functions mutate the
monitor ``TestSuite``, its ``JobSchedule``, and the table-group link, and raise
stdlib exceptions — the MCP and UI layers translate those into their own
user-facing errors.
"""

import logging
from typing import Any

from sqlalchemy import func, select

from testgen.commands.test_generation import run_monitor_generation
from testgen.common.models import get_current_session
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_result import TestResult
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite

LOG = logging.getLogger("testgen")

# Monitors generated when monitoring is first enabled. Freshness_Trend depends on
# per-table freshness fingerprinting and is generated separately, so it is not part
# of the initial bootstrap set.
INITIAL_MONITOR_TYPES = ["Volume_Trend", "Schema_Drift"]

# Default monitor configuration applied at bootstrap, mirroring the UI's setup form.
_DEFAULT_SUITE_ATTRS: dict[str, Any] = {
    "monitor_lookback": 14,
    "monitor_regenerate_freshness": True,
    "predict_min_lookback": 30,
    "predict_sensitivity": "medium",
    "predict_exclude_weekends": False,
    "predict_holiday_codes": None,
}

# The monitor-configuration columns callers may set via ``suite_attrs``. Used as a
# whitelist so a caller's dict (e.g. a UI form payload) can't write arbitrary suite columns.
_MONITOR_SETTING_COLUMNS = tuple(_DEFAULT_SUITE_ATTRS)


def enable_monitoring(
    table_group: TableGroup,
    cron_expr: str,
    cron_tz: str = "UTC",
    *,
    suite_attrs: dict[str, Any] | None = None,
    active: bool = True,
) -> tuple[TestSuite, int]:
    """Bootstrap monitoring for a table group.

    Creates the monitor test suite, generates the initial monitors, creates the
    run-monitors schedule, and links the suite to the table group.

    ``suite_attrs`` overrides the default monitor configuration.

    Returns ``(monitor_suite, monitor_count)``. Raises ``ValueError`` if the table
    group already has monitoring enabled.
    """
    if table_group.monitor_test_suite_id:
        raise ValueError("Monitoring is already enabled for this table group.")

    provided = suite_attrs or {}
    attrs = dict(_DEFAULT_SUITE_ATTRS)
    for key in _MONITOR_SETTING_COLUMNS:
        if (value := provided.get(key)) is not None:
            attrs[key] = value

    monitor_suite = TestSuite(
        project_code=table_group.project_code,
        test_suite=f"{table_group.table_groups_name} Monitors",
        connection_id=table_group.connection_id,
        table_groups_id=table_group.id,
        export_to_observability=False,
        dq_score_exclude=True,
        is_monitor=True,
        **attrs,
    )
    monitor_suite.save()

    JobSchedule(
        project_code=table_group.project_code,
        key=RUN_MONITORS_JOB_KEY,
        kwargs={"test_suite_id": str(monitor_suite.id)},
        cron_expr=cron_expr,
        cron_tz=cron_tz,
        active=active,
    ).save()

    table_group.monitor_test_suite_id = monitor_suite.id
    table_group.save()

    # Commit needed to make the test suite visible to run_monitor_generation's separate DB connection.
    get_current_session().commit()
    run_monitor_generation(monitor_suite.id, INITIAL_MONITOR_TYPES)

    count = get_current_session().scalar(
        select(func.count()).select_from(TestDefinition).where(TestDefinition.test_suite_id == monitor_suite.id)
    )
    return monitor_suite, count or 0


def update_monitoring(
    monitor_suite: TestSuite,
    schedule: JobSchedule,
    *,
    suite_attrs: dict[str, Any] | None = None,
    cron_expr: str | None = None,
    cron_tz: str | None = None,
    active: bool | None = None,
) -> None:
    """Apply a partial update to monitor settings and/or schedule.

    ``suite_attrs`` maps monitor ``TestSuite`` columns to new values; only the keys in
    ``_MONITOR_SETTING_COLUMNS`` that are present are applied (a present ``None`` clears
    the column). Supplied schedule fields are updated in place. Does not commit — the
    caller's session lifecycle does.
    """
    provided = suite_attrs or {}
    for key in _MONITOR_SETTING_COLUMNS:
        if key in provided:
            setattr(monitor_suite, key, provided[key])
    monitor_suite.save()

    if cron_expr is not None:
        schedule.cron_expr = cron_expr
    if cron_tz is not None:
        schedule.cron_tz = cron_tz
    if active is not None:
        schedule.active = active
    schedule.save()


def disable_monitoring(monitor_suite: TestSuite) -> dict[str, int]:
    """Remove a monitor suite and all its monitors, runs, and history.

    Counts what will be removed before cascading the delete. Returns counts keyed
    ``monitors`` (test definitions), ``events`` (test results), and ``runs``.
    """
    session = get_current_session()
    suite_id = monitor_suite.id
    counts = {
        "monitors": session.scalar(
            select(func.count()).select_from(TestDefinition).where(TestDefinition.test_suite_id == suite_id)
        )
        or 0,
        "events": session.scalar(
            select(func.count()).select_from(TestResult).where(TestResult.test_suite_id == suite_id)
        )
        or 0,
        "runs": session.scalar(
            select(func.count()).select_from(TestRun).where(TestRun.test_suite_id == suite_id)
        )
        or 0,
    }
    TestSuite.cascade_delete([suite_id])
    return counts
