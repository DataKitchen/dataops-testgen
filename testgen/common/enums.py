"""Shared enums used across multiple models, services, and surfaces.

Add an enum here when its values are referenced by more than one model file or by
both the model layer and an outer surface (MCP, API, UI). Single-model enums live
in their model file.
"""
from collections.abc import Iterable
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
    run_monitor_generation = "run-monitor-generation"
    run_score_update = "run-score-update"
    recalculate_project_scores = "recalculate-project-scores"
    run_data_cleanup = "run-data-cleanup"


# Job keys whose handler checks for a pause request at a work-key boundary and persists resume
# state before exiting. List a key here only for a handler built on ``PausableJob``: one that
# cannot actually observe the request never stops early, and holds shutdown open for the rest
# of its run.
PAUSABLE_JOB_KEYS: frozenset[JobKey] = frozenset({JobKey.run_profile})


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
    """``status`` column values for ``job_executions``.

    The lifecycle graph in ``_TRANSITIONS`` below is the single declaration of how a job may
    move between these, and the classifications are read off it: a status with nowhere left
    to go is terminal, and one that can reach CLAIMED is claimable.
    """
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    INTERRUPT_REQUESTED = "interrupt_requested"
    INTERRUPTED = "interrupted"

    @classmethod
    def sources_for(cls, target: "JobStatus") -> tuple["JobStatus", ...]:
        """Statuses a job may hold for a transition to ``target`` to be allowed."""
        return _in_declaration_order(source for source, targets in _TRANSITIONS.items() if target in targets)

    @classmethod
    def terminal(cls) -> tuple["JobStatus", ...]:
        """Statuses a job never leaves."""
        return _TERMINAL

    @classmethod
    def active(cls) -> tuple["JobStatus", ...]:
        """Statuses that represent live work: it blocks a duplicate run and is never purged."""
        return _ACTIVE

    @classmethod
    def claimable(cls) -> tuple["JobStatus", ...]:
        """Statuses the scheduler may pick up and hand to a worker."""
        return _CLAIMABLE

    @classmethod
    def stale_recoverable(cls) -> tuple["JobStatus", ...]:
        """Statuses a restart must settle, because they imply a process that is now gone.

        Two active statuses are excluded, for reasons the graph cannot express: PENDING was
        never claimed, so no process died and the next poll starts it normally, and INTERRUPTED
        is already queued for the next poll to claim.
        """
        return _STALE_RECOVERABLE


# User-facing display labels for JobStatus values.
JOB_STATUS_LABEL: dict[str, str] = {
    JobStatus.COMPLETED: "Completed",
    JobStatus.CANCELED: "Canceled",
    JobStatus.CANCEL_REQUESTED: "Canceling",
    JobStatus.PENDING: "Pending",
    JobStatus.CLAIMED: "Starting",
    JobStatus.RUNNING: "Running",
    JobStatus.ERROR: "Error",
    JobStatus.INTERRUPT_REQUESTED: "Interrupting",
    JobStatus.INTERRUPTED: "Interrupted",
}


# The job lifecycle. A status absent from this mapping, or mapped to nothing, is terminal.
_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.CLAIMED, JobStatus.CANCEL_REQUESTED}),
    JobStatus.CLAIMED: frozenset({JobStatus.RUNNING, JobStatus.ERROR, JobStatus.CANCEL_REQUESTED}),
    JobStatus.RUNNING: frozenset({
        JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCEL_REQUESTED, JobStatus.INTERRUPT_REQUESTED,
    }),
    # The CANCEL_REQUESTED self-loop makes requesting a cancel idempotent.
    JobStatus.CANCEL_REQUESTED: frozenset({JobStatus.CANCELED, JobStatus.CANCEL_REQUESTED}),
    # An interrupt request races the run finishing, failing, or being canceled, and all three
    # must still be able to settle or the row is stranded with no process behind it. The
    # self-loop makes requesting an interrupt idempotent.
    JobStatus.INTERRUPT_REQUESTED: frozenset({
        JobStatus.INTERRUPTED, JobStatus.COMPLETED, JobStatus.ERROR,
        JobStatus.CANCEL_REQUESTED, JobStatus.INTERRUPT_REQUESTED,
    }),
    # Claimable, like PENDING: an interrupted run is queued work that the next poll picks up.
    # The checkpoint on the row is what tells the two apart.
    JobStatus.INTERRUPTED: frozenset({
        JobStatus.CLAIMED, JobStatus.CANCEL_REQUESTED, JobStatus.INTERRUPTED,
    }),
}


def _in_declaration_order(statuses: Iterable[JobStatus]) -> tuple[JobStatus, ...]:
    """Order statuses by declaration, so an ``IN`` clause reads the same every time."""
    wanted = set(statuses)
    return tuple(status for status in JobStatus if status in wanted)


_TERMINAL: tuple[JobStatus, ...] = _in_declaration_order(
    status for status in JobStatus if not _TRANSITIONS.get(status)
)
_ACTIVE: tuple[JobStatus, ...] = _in_declaration_order(set(JobStatus) - set(_TERMINAL))
_CLAIMABLE: tuple[JobStatus, ...] = JobStatus.sources_for(JobStatus.CLAIMED)
_STALE_RECOVERABLE: tuple[JobStatus, ...] = _in_declaration_order(
    set(_ACTIVE) - {JobStatus.PENDING, JobStatus.INTERRUPTED}
)

# Statuses reached only by way of an interrupt request, so a job whose key is not in
# ``PAUSABLE_JOB_KEYS`` never holds one.
INTERRUPT_STATUSES: frozenset[JobStatus] = frozenset({
    JobStatus.INTERRUPT_REQUESTED, JobStatus.INTERRUPTED,
})


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
