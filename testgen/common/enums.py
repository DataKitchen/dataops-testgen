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


class JobKey(StrEnum):
    """``job_key`` column values for ``job_executions`` and ``job_schedules``."""
    run_profile = "run-profile"
    run_tests = "run-tests"
    run_monitors = "run-monitors"
    run_test_generation = "run-test-generation"


class JobSource(StrEnum):
    """``source`` column values for ``job_executions``. Identifies which surface
    submitted the job — API client, UI, scheduler, MCP tool, CLI, or backfill."""
    api = "api"
    ui = "ui"
    scheduler = "scheduler"
    mcp = "mcp"
    cli = "cli"
    backfill = "backfill"


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
