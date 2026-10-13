"""API v1 — a table group's monitoring configuration."""

from collections.abc import Collection
from datetime import UTC
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Response

from testgen.api.deps import api_error, api_errors, db_session, fields_to_change, resolve_table_group
from testgen.api.enums import MonitorSensitivity
from testgen.api.schemas import ErrorResponse, MonitoringConfig, MonitoringResponse, MonitoringUpdate
from testgen.common.cron_service import describe_cron, normalize_cron, validate_schedule
from testgen.common.enums import SuiteType
from testgen.common.models import get_current_session
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.monitor_service import (
    MONITOR_SETTING_PUBLIC_NAMES,
    canonical_holiday_codes,
    count_monitors,
    create_monitor_schedule,
    enable_monitoring,
    lock_monitor_link,
    update_monitoring,
    validate_monitor_settings,
)

_error_responses = {404: {"model": ErrorResponse, "description": "Not found, or monitoring is not enabled"}}
_invalid_response = {400: {"model": ErrorResponse, "description": "One entry per invalid setting or schedule field"}}

# Request field → monitor TestSuite column.
_SETTING_COLUMNS = {public: column for column, public in MONITOR_SETTING_PUBLIC_NAMES.items()}

_SCHEDULE_FIELD_NAMES = {"cron_expr": "cron_expression", "cron_tz": "timezone"}

router = APIRouter(tags=["Monitors"], dependencies=[Depends(db_session, scope="function")], responses=_error_responses)


@router.get(
    "/table-groups/{table_group_id}/monitoring",
    response_model=MonitoringResponse,
    summary="Read a table group's monitoring",
)
def get_monitoring(table_group: TableGroup = resolve_table_group("view")):  # noqa: B008
    """The table group's monitor settings and schedule, and how many monitors it has.
    Returns 404 when monitoring is not enabled.
    """
    monitor_suite, schedule = _require_monitoring(table_group)
    return _to_response(table_group, monitor_suite, schedule)


@router.put(
    "/table-groups/{table_group_id}/monitoring",
    response_model=MonitoringResponse,
    summary="Enable or replace a table group's monitoring",
    responses={**_invalid_response, 201: {"model": MonitoringResponse, "description": "Monitoring was enabled"}},
)
def put_monitoring(
    response: Response,
    table_group: TableGroup = resolve_table_group("edit"),  # noqa: B008
    body: MonitoringConfig = Body(...),  # noqa: B008
) -> MonitoringResponse:
    """Enable monitoring for a table group, or replace its configuration when it is already enabled.

    Enabling returns 201: it creates the table group's initial Volume and Schema monitors and the
    schedule they run on. Freshness monitors follow once the table group has profiling data.
    When monitoring is already enabled, the settings and schedule are replaced, settings left out of
    the body return to their defaults, and the existing monitors and their history are kept (200).
    A paused schedule stays paused; resume it with PATCH.
    """
    settings = _settings(body, body.model_fields)
    _validate(body.cron_expression, body.timezone, settings)
    settings = _canonical(settings)
    cron_expr = normalize_cron(body.cron_expression)

    # The lock makes a concurrent or retried PUT wait for this one, then take the replace path.
    monitor_suite_id = lock_monitor_link(table_group)
    monitor_suite = _monitor_suite(monitor_suite_id)
    monitor_count = None
    if monitor_suite is None:
        monitor_suite, monitor_count = enable_monitoring(table_group, cron_expr, body.timezone, suite_attrs=settings)
        schedule = JobSchedule.get_for_monitor_suite(monitor_suite.id)
        response.status_code = 201
    else:
        schedule = JobSchedule.get_for_monitor_suite(monitor_suite.id)
        if schedule is None:
            schedule = create_monitor_schedule(monitor_suite, cron_expr, body.timezone)
        update_monitoring(monitor_suite, schedule, suite_attrs=settings, cron_expr=cron_expr, cron_tz=body.timezone)

    get_current_session().flush()
    return _to_response(table_group, monitor_suite, schedule, monitor_count=monitor_count)


@router.patch(
    "/table-groups/{table_group_id}/monitoring",
    response_model=MonitoringResponse,
    summary="Update a table group's monitoring",
    responses=_invalid_response,
)
def patch_monitoring(
    table_group: TableGroup = resolve_table_group("edit"),  # noqa: B008
    body: MonitoringUpdate = Body(...),  # noqa: B008
) -> MonitoringResponse:
    """Change some of a table group's monitor settings or its schedule, leaving the rest as they are.

    Send `active` to pause or resume the monitor schedule. Returns 404 when monitoring is not enabled.
    """
    fields_to_change(body)
    monitor_suite, schedule = _require_monitoring(table_group)

    sent = body.model_fields_set
    settings = _settings(body, sent)
    cron_expr = body.cron_expression if "cron_expression" in sent else None
    cron_tz = body.timezone if "timezone" in sent else None
    if cron_expr is not None or cron_tz is not None:
        _validate(
            cron_expr if cron_expr is not None else schedule.cron_expr,
            cron_tz if cron_tz is not None else schedule.cron_tz,
            settings,
        )
        cron_expr = normalize_cron(cron_expr) if cron_expr is not None else None
    else:
        _validate(None, None, settings)
    settings = _canonical(settings)

    active = body.active if "active" in sent else None
    update_monitoring(
        monitor_suite, schedule, suite_attrs=settings, cron_expr=cron_expr, cron_tz=cron_tz, active=active
    )
    get_current_session().flush()
    return _to_response(table_group, monitor_suite, schedule)


def _settings(body: MonitoringConfig | MonitoringUpdate, fields: Collection[str]) -> dict[str, Any]:
    """Map the body's settings among ``fields`` to monitor TestSuite columns."""
    settings: dict[str, Any] = {}
    for name, column in _SETTING_COLUMNS.items():
        if name not in fields:
            continue
        value = getattr(body, name)
        settings[column] = value.value if name == "sensitivity" else value
    return settings


def _validate(cron_expr: str | None, cron_tz: str | None, settings: dict[str, Any]) -> None:
    """Raise a 400 listing every invalid schedule field and setting."""
    errors: list[str] = []
    if cron_expr is not None or cron_tz is not None:
        errors = validate_schedule(cron_expr, cron_tz, field_names=_SCHEDULE_FIELD_NAMES)
    errors.extend(validate_monitor_settings(settings))
    if errors:
        raise api_errors(400, "invalid_monitoring", errors)


def _canonical(settings: dict[str, Any]) -> dict[str, Any]:
    """Return ``settings`` with any holiday codes in canonical form. Call after ``_validate``."""
    if "predict_holiday_codes" not in settings:
        return settings
    return {**settings, "predict_holiday_codes": canonical_holiday_codes(settings["predict_holiday_codes"])}


def _monitor_suite(monitor_suite_id: UUID | None) -> TestSuite | None:
    if not monitor_suite_id:
        return None
    return TestSuite.get(monitor_suite_id, TestSuite.suite_type == SuiteType.MONITOR)


def _require_monitoring(table_group: TableGroup) -> tuple[TestSuite, JobSchedule]:
    monitor_suite = _monitor_suite(table_group.monitor_test_suite_id)
    schedule = JobSchedule.get_for_monitor_suite(monitor_suite.id) if monitor_suite else None
    if monitor_suite is None or schedule is None:
        raise api_error(404, "monitoring_not_enabled", "Monitoring is not enabled for this table group.")
    return monitor_suite, schedule


def _to_response(
    table_group: TableGroup, monitor_suite: TestSuite, schedule: JobSchedule, *, monitor_count: int | None = None
) -> MonitoringResponse:
    sensitivity = monitor_suite.predict_sensitivity
    if sensitivity is not None:
        sensitivity = MonitorSensitivity(getattr(sensitivity, "value", sensitivity))
    return MonitoringResponse(
        table_group_id=table_group.id,
        monitor_count=count_monitors(monitor_suite) if monitor_count is None else monitor_count,
        cron_expression=schedule.cron_expr,
        timezone=schedule.cron_tz,
        description=describe_cron(schedule.cron_expr),
        active=bool(schedule.active),
        next_run_at=schedule.get_sample_triggering_timestamps(1)[0].astimezone(UTC) if schedule.active else None,
        lookback_runs=monitor_suite.monitor_lookback,
        regenerate_freshness=monitor_suite.monitor_regenerate_freshness,
        min_training_lookback=monitor_suite.predict_min_lookback,
        sensitivity=sensitivity,
        exclude_weekends=monitor_suite.predict_exclude_weekends,
        holiday_codes=monitor_suite.holiday_codes_list or [],
    )
