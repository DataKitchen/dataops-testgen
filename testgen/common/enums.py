"""Shared enums used across multiple models, services, and surfaces.

Add an enum here when its values are referenced by more than one model file or by
both the model layer and an outer surface (MCP, API, UI). Single-model enums live
in their model file.
"""
from enum import StrEnum


class QualityDimension(StrEnum):
    """Stored ``dq_dimension`` values shared by ``profile_anomaly_types`` and ``test_types``.
    Surfaced to users as "Quality Dimension"."""
    ACCURACY = "Accuracy"
    COMPLETENESS = "Completeness"
    CONSISTENCY = "Consistency"
    RECENCY = "Recency"
    TIMELINESS = "Timeliness"
    UNIQUENESS = "Uniqueness"
    VALIDITY = "Validity"


class ImpactDimension(StrEnum):
    """Stored ``impact_dimension`` values shared by ``profile_anomaly_types`` /
    ``profile_anomaly_results`` and ``test_types``. The primary dimension breakdown
    used by scorecards."""
    RELIABILITY = "Reliability"
    CONFORMANCE = "Conformance"
    REGULARITY = "Regularity"
    USABILITY = "Usability"


class HealthDimension(StrEnum):
    """Stored ``health_dimension`` values for ``test_types``. The monitor-style axis
    that groups test types by what class of data-health problem they detect."""
    SCHEMA_DRIFT = "Schema Drift"
    DATA_DRIFT = "Data Drift"
    STATISTICAL_DRIFT = "Statistical Drift"
    VOLUME = "Volume"
    FRESHNESS = "Freshness"


class JobKey(StrEnum):
    """``job_key`` column values for ``job_executions`` and ``job_schedules``."""
    run_profile = "run-profile"
    run_tests = "run-tests"
    run_monitors = "run-monitors"
    run_test_generation = "run-test-generation"
    run_score_update = "run-score-update"
    recalculate_project_scores = "recalculate-project-scores"
    run_data_cleanup = "run-data-cleanup"


class PublicJobKey(StrEnum):
    """``job_key`` values exposed through the public API — the externally-triggerable
    subset of ``JobKey``. Internal maintenance kinds are intentionally absent."""
    run_profile = JobKey.run_profile.value
    run_tests = JobKey.run_tests.value
    run_test_generation = JobKey.run_test_generation.value


class JobSource(StrEnum):
    """``source`` column values for ``job_executions``."""
    api = "api"
    ui = "ui"
    scheduler = "scheduler"
    mcp = "mcp"
    cli = "cli"
    system = "system"


class JobStatus(StrEnum):
    """``status`` column values for ``job_executions``. Lifecycle states; see
    ``job_execution.py`` for the transition rules."""
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"


# User-facing display labels for JobStatus values.
JOB_STATUS_LABEL: dict[str, str] = {
    JobStatus.COMPLETED: "Completed",
    JobStatus.CANCELED: "Canceled",
    JobStatus.CANCEL_REQUESTED: "Canceling",
    JobStatus.PENDING: "Pending",
    JobStatus.CLAIMED: "Starting",
    JobStatus.RUNNING: "Running",
    JobStatus.ERROR: "Error",
}


class Disposition(StrEnum):
    """Stored disposition values for ``profile_anomaly_results.disposition`` and
    ``test_results.disposition``. The user-facing label for ``INACTIVE`` is "Muted"."""
    CONFIRMED = "Confirmed"
    DISMISSED = "Dismissed"
    INACTIVE = "Inactive"


class IssueLikelihood(StrEnum):
    """Stored ``profile_anomaly_types.issue_likelihood`` values."""
    DEFINITE = "Definite"
    LIKELY = "Likely"
    POSSIBLE = "Possible"
    POTENTIAL_PII = "Potential PII"


class PiiRisk(StrEnum):
    """Risk level extracted from PII issue ``detail`` strings via ``priority`` hybrid."""
    HIGH = "High"
    MODERATE = "Moderate"


# ``data_column_chars.pii_flag`` and ``profile_results.pii_flag`` store strings shaped like
# ``A/NAME/full_name`` — a single-character risk prefix, a category, and a detail. The prefix
# maps to a human-readable label used across the MCP tools, REST API, and (as a source of
# truth for) the frontend. The stored ``MANUAL`` sentinel means the classification was set
# by hand and has no prefix.
#
# Hygiene *findings* (``HygieneIssue.priority``) never surface the ``Low`` level — the regex
# in ``hygiene_issue.py`` parses only ``HIGH`` and ``MODERATE`` from ``detail`` strings. The
# ``Low`` bucket applies only to column classifications.
PII_FLAG_PREFIX_TO_LABEL: dict[str, str] = {"A": "High", "B": "Moderate", "C": "Low"}


class MonitorType(StrEnum):
    """Stored ``test_type`` values for the four monitor test types. Surfaced to users
    as the lowercase short labels (freshness / volume / schema / metric)."""
    FRESHNESS = "Freshness_Trend"
    VOLUME = "Volume_Trend"
    SCHEMA = "Schema_Drift"
    METRIC = "Metric_Trend"


class MonitorCalculation(StrEnum):
    """Values stored in ``TestDefinition.history_calculation``, optionally mirrored in
    ``.history_calculation_upper``.

    ``PREDICT`` selects Prediction Model mode and is only ever stored in
    ``history_calculation`` — ``history_calculation_upper`` is cleared to ``None``
    alongside it. The remaining members are the Historical Calculation options and
    may appear in either column; when the choice is ``EXPRESSION``, the SQL
    expression is wrapped as ``EXPR:[...]`` before storage — see
    ``testgen/common/history_calculation_service.py``.
    """
    PREDICT = "PREDICT"
    VALUE = "Value"
    MINIMUM = "Minimum"
    MAXIMUM = "Maximum"
    SUM = "Sum"
    AVERAGE = "Average"
    EXPRESSION = "Expression"
