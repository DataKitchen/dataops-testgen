"""Lowercase presentation enums for API v1 request filters and responses.

Shared home for StrEnums that map a DB-stored value to the lowercase snake_case
form exposed through the API. Several DB columns store title-case values
(``test_results.result_status``, ``*.disposition``); the mapping dicts here are the
single seam that normalizes them to the API surface — the DB is never changed.
"""

from enum import StrEnum

from testgen.common.enums import Disposition as DbDisposition
from testgen.common.enums import MonitorType as DbMonitorType
from testgen.common.models.test_definition import ThresholdMode
from testgen.common.models.test_result import TestResultStatus


class ResultStatus(StrEnum):
    """Outcome of a single test result."""

    passed = "passed"
    failed = "failed"
    warning = "warning"
    error = "error"
    log = "log"


class Disposition(StrEnum):
    """Triage state of a test result. ``no_decision`` is the state of a result no one
    has triaged yet. Omitting the filter returns active results (``confirmed`` and
    ``no_decision``); pass an explicit value to filter to a single state."""

    confirmed = "confirmed"
    dismissed = "dismissed"
    muted = "muted"
    no_decision = "no_decision"


RESULT_STATUS_TO_DB: dict[ResultStatus, TestResultStatus] = {
    ResultStatus.passed: TestResultStatus.Passed,
    ResultStatus.failed: TestResultStatus.Failed,
    ResultStatus.warning: TestResultStatus.Warning,
    ResultStatus.error: TestResultStatus.Error,
    ResultStatus.log: TestResultStatus.Log,
}
RESULT_STATUS_FROM_DB: dict[TestResultStatus, ResultStatus] = {v: k for k, v in RESULT_STATUS_TO_DB.items()}

# ``no_decision`` has no stored DB value — it corresponds to a NULL ``disposition``
# column, handled explicitly at the API boundary (not present in these dicts).
DISPOSITION_TO_DB: dict[Disposition, DbDisposition] = {
    Disposition.confirmed: DbDisposition.CONFIRMED,
    Disposition.dismissed: DbDisposition.DISMISSED,
    Disposition.muted: DbDisposition.INACTIVE,
}
DISPOSITION_FROM_DB: dict[DbDisposition, Disposition] = {v: k for k, v in DISPOSITION_TO_DB.items()}


class MonitorType(StrEnum):
    """The kind of signal a monitor tracks."""

    freshness = "freshness"
    volume = "volume"
    schema = "schema"
    metric = "metric"


class TableState(StrEnum):
    """Structural change observed for a monitored table within the lookback window."""

    added = "added"
    dropped = "dropped"
    modified = "modified"


class MonitorThresholdMode(StrEnum):
    """How a monitor's thresholds are derived. ``not_applicable`` covers schema monitors,
    which are presence-only and carry no thresholds."""

    prediction_model = "prediction_model"
    historical_calculation = "historical_calculation"
    static = "static"
    not_applicable = "not_applicable"


class SortOrder(StrEnum):
    """Sort direction for list endpoints."""

    asc = "asc"
    desc = "desc"


class MonitorSortField(StrEnum):
    """Sortable fields for the per-table monitoring summary."""

    table_name = "table_name"
    freshness_anomalies = "freshness_anomalies"
    volume_anomalies = "volume_anomalies"
    schema_anomalies = "schema_anomalies"
    metric_anomalies = "metric_anomalies"
    latest_update = "latest_update"
    row_count = "row_count"


MONITOR_TYPE_TO_DB: dict[MonitorType, DbMonitorType] = {
    MonitorType.freshness: DbMonitorType.FRESHNESS,
    MonitorType.volume: DbMonitorType.VOLUME,
    MonitorType.schema: DbMonitorType.SCHEMA,
    MonitorType.metric: DbMonitorType.METRIC,
}
MONITOR_TYPE_FROM_DB: dict[DbMonitorType, MonitorType] = {v: k for k, v in MONITOR_TYPE_TO_DB.items()}


THRESHOLD_MODE_FROM_DB: dict[ThresholdMode, MonitorThresholdMode] = {
    ThresholdMode.PREDICTION: MonitorThresholdMode.prediction_model,
    ThresholdMode.HISTORICAL: MonitorThresholdMode.historical_calculation,
    ThresholdMode.STATIC: MonitorThresholdMode.static,
    ThresholdMode.NONE: MonitorThresholdMode.not_applicable,
}


def threshold_mode_from_db(mode: ThresholdMode) -> MonitorThresholdMode:
    """Map a derived monitor threshold-mode to the API threshold mode."""
    return THRESHOLD_MODE_FROM_DB[mode]


def monitor_sort_to_model(sort: MonitorSortField, order: SortOrder) -> str:
    """Translate ``(sort, order)`` to the model's ``sort_by`` form (``field`` / ``field_desc``)."""
    return f"{sort.value}_desc" if order == SortOrder.desc else sort.value
