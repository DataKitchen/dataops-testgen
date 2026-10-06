"""Monitor lifecycle: enable, update, and disable monitoring for a table group.

Shared by the MCP tools, the monitors dashboard, and the table-group creation
wizard so all three drive monitoring through one path. Functions mutate the
monitor ``TestSuite``, its ``JobSchedule``, and the table-group link, and raise
stdlib exceptions — the MCP and UI layers translate those into their own
user-facing errors.
"""

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func, select

from testgen.commands.test_generation import run_monitor_generation
from testgen.common.enums import MonitorType, SuiteType
from testgen.common.holiday_service import (
    canonicalize_holiday_code,
    is_supported_holiday_code,
    list_market_holiday_codes,
)
from testgen.common.models import get_current_session
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_result import TestResult
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import MONITOR_SETTING_DEFAULTS, PredictSensitivity, TestSuite

LOG = logging.getLogger("testgen")

# Monitors generated when monitoring is first enabled. Freshness_Trend depends on
# per-table freshness fingerprinting and is generated separately, so it is not part
# of the initial bootstrap set.
INITIAL_MONITOR_TYPES = [MonitorType.VOLUME.value, MonitorType.SCHEMA.value]

_DEFAULT_SUITE_ATTRS: dict[str, Any] = MONITOR_SETTING_DEFAULTS

# The monitor-configuration columns callers may set via ``suite_attrs``. Used as a
# whitelist so a caller's dict (e.g. a UI form payload) can't write arbitrary suite columns.
_MONITOR_SETTING_COLUMNS = tuple(_DEFAULT_SUITE_ATTRS)

LOOKBACK_RUNS_RANGE = (1, 200)
MIN_TRAINING_LOOKBACK_RANGE = (20, 1000)

_PUBLIC_FIELD_NAMES = {
    "monitor_lookback": "lookback_runs",
    "monitor_regenerate_freshness": "regenerate_freshness",
    "predict_min_lookback": "min_training_lookback",
    "predict_sensitivity": "sensitivity",
    "predict_exclude_weekends": "exclude_weekends",
    "predict_holiday_codes": "holiday_codes",
}


def validate_monitor_settings(suite_attrs: Mapping[str, Any]) -> list[str]:
    """Return every reason a monitor configuration cannot be stored (empty list = valid).

    Args:
        suite_attrs: Monitor ``TestSuite`` columns to check, as passed to ``enable_monitoring``
            or ``update_monitoring``. Absent or ``None`` values are not checked.

    Messages name the settings by their public names (``lookback_runs``, ``sensitivity``, ...).
    """
    errors: list[str] = []

    def field(attr: str) -> str:
        return f"`{_PUBLIC_FIELD_NAMES[attr]}`"

    for attr, (low, high) in (
        ("monitor_lookback", LOOKBACK_RUNS_RANGE),
        ("predict_min_lookback", MIN_TRAINING_LOOKBACK_RANGE),
    ):
        value = suite_attrs.get(attr)
        if value is not None and not low <= value <= high:
            errors.append(f"{field(attr)} must be between {low} and {high}.")

    sensitivity = suite_attrs.get("predict_sensitivity")
    if sensitivity is not None and sensitivity not in {member.value for member in PredictSensitivity}:
        valid = ", ".join(member.value for member in PredictSensitivity)
        errors.append(f"{field('predict_sensitivity')} must be one of {valid}.")

    codes = suite_attrs.get("predict_holiday_codes")
    if codes is not None and (unknown := [code for code in codes if not is_supported_holiday_code(code.strip())]):
        errors.append(
            f"{field('predict_holiday_codes')} has unknown codes: {', '.join(unknown)}. Countries use ISO 3166-1 "
            f"alpha-2 codes (e.g. `US`, `GB`); financial markets use one of: {', '.join(list_market_holiday_codes())}."
        )

    return errors


def canonical_holiday_codes(codes: Iterable[str]) -> list[str] | None:
    """Return supported holiday codes in canonical form, blanks and duplicates dropped; ``None`` when none remain."""
    canonical = [canonicalize_holiday_code(code.strip()) for code in codes if code.strip()]
    return list(dict.fromkeys(canonical)) or None


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

    The initial monitors are generated in the caller's session, so nothing is committed
    here and the whole bootstrap rolls back with it.

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
        suite_type=SuiteType.MONITOR,
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

    run_monitor_generation(monitor_suite.id, INITIAL_MONITOR_TYPES, in_session=True)

    return monitor_suite, count_monitors(monitor_suite)


def count_monitors(monitor_suite: TestSuite) -> int:
    """Return the number of monitors in a monitor suite."""
    return get_current_session().scalar(
        select(func.count())
        .select_from(TestDefinition)
        .where(TestDefinition.test_suite_id == monitor_suite.id, TestDefinition.version_clause())
    ) or 0


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
