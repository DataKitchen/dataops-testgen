"""Lowercase presentation enums for API v1 request filters and responses.

Shared home for StrEnums that map a DB-stored value to the lowercase snake_case
form exposed through the API. Several DB columns store title-case values
(``test_results.result_status``, ``*.disposition``); the mapping dicts here are the
single seam that normalizes them to the API surface — the DB is never changed.
"""

from enum import StrEnum

from testgen.common.enums import Disposition as DbDisposition
from testgen.common.enums import ImpactDimension as DbImpactDimension
from testgen.common.enums import IssueLikelihood as DbIssueLikelihood
from testgen.common.enums import MonitorType as DbMonitorType
from testgen.common.enums import PiiRisk as DbPiiRisk
from testgen.common.enums import QualityDimension as DbQualityDimension
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


class HygieneDisposition(StrEnum):
    """Triage state of a hygiene issue.

    Hygiene issues COALESCE NULL disposition to ``Confirmed`` in every read path,
    so there is no ``no_decision`` state to surface. Omitting the filter or passing
    ``confirmed`` both return rows whose stored disposition is ``Confirmed`` or NULL."""

    confirmed = "confirmed"
    dismissed = "dismissed"
    muted = "muted"


class IssueLikelihood(StrEnum):
    """Likelihood category of a data-quality hygiene issue. The ``Potential PII``
    likelihood is not exposed here — PII findings live behind a dedicated endpoint
    with its own ``PiiRisk`` filter."""

    definite = "definite"
    likely = "likely"
    possible = "possible"


class PiiRisk(StrEnum):
    """Risk level of a Potential PII finding, extracted from the issue ``detail``."""

    high = "high"
    moderate = "moderate"


class ImpactDimension(StrEnum):
    """Impact-dimension classification shared by hygiene issues and test types."""

    reliability = "reliability"
    conformance = "conformance"
    regularity = "regularity"
    usability = "usability"


class QualityDimension(StrEnum):
    """Data-quality dimension shared by hygiene issues and test types.

    Emitted only as breakdown row values when the scores endpoint is called with
    ``group_by=quality_dimension``. Not accepted as a request filter."""

    accuracy = "accuracy"
    completeness = "completeness"
    consistency = "consistency"
    recency = "recency"
    timeliness = "timeliness"
    uniqueness = "uniqueness"
    validity = "validity"


class ScoreType(StrEnum):
    """Which score the ``scores`` endpoint breakdown is scored against."""

    total = "total"
    cde = "cde"


class ScoresGroupBy(StrEnum):
    """Attribute the ``scores`` endpoint breaks the score down by.

    ``impact_dimension`` is the recommended primary breakdown. ``quality_dimension``,
    ``impact_dimension`` and ``table_group`` are groupable only; every other value is
    also accepted as a filter query param."""

    quality_dimension = "quality_dimension"
    impact_dimension = "impact_dimension"
    table_group = "table_group"
    data_source = "data_source"
    business_domain = "business_domain"
    source_system = "source_system"
    source_process = "source_process"
    stakeholder_group = "stakeholder_group"
    transform_level = "transform_level"
    data_location = "data_location"
    data_product = "data_product"
    semantic_data_type = "semantic_data_type"
    data_classification = "data_classification"


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


HYGIENE_DISPOSITION_TO_DB: dict[HygieneDisposition, DbDisposition] = {
    HygieneDisposition.confirmed: DbDisposition.CONFIRMED,
    HygieneDisposition.dismissed: DbDisposition.DISMISSED,
    HygieneDisposition.muted: DbDisposition.INACTIVE,
}
HYGIENE_DISPOSITION_FROM_DB: dict[DbDisposition, HygieneDisposition] = {
    v: k for k, v in HYGIENE_DISPOSITION_TO_DB.items()
}

LIKELIHOOD_TO_DB: dict[IssueLikelihood, DbIssueLikelihood] = {
    IssueLikelihood.definite: DbIssueLikelihood.DEFINITE,
    IssueLikelihood.likely: DbIssueLikelihood.LIKELY,
    IssueLikelihood.possible: DbIssueLikelihood.POSSIBLE,
}
LIKELIHOOD_FROM_DB: dict[DbIssueLikelihood, IssueLikelihood] = {v: k for k, v in LIKELIHOOD_TO_DB.items()}

PII_RISK_TO_DB: dict[PiiRisk, DbPiiRisk] = {
    PiiRisk.high: DbPiiRisk.HIGH,
    PiiRisk.moderate: DbPiiRisk.MODERATE,
}
PII_RISK_FROM_DB: dict[DbPiiRisk, PiiRisk] = {v: k for k, v in PII_RISK_TO_DB.items()}

IMPACT_DIMENSION_TO_DB: dict[ImpactDimension, DbImpactDimension] = {
    ImpactDimension.reliability: DbImpactDimension.RELIABILITY,
    ImpactDimension.conformance: DbImpactDimension.CONFORMANCE,
    ImpactDimension.regularity: DbImpactDimension.REGULARITY,
    ImpactDimension.usability: DbImpactDimension.USABILITY,
}
IMPACT_DIMENSION_FROM_DB: dict[DbImpactDimension, ImpactDimension] = {
    v: k for k, v in IMPACT_DIMENSION_TO_DB.items()
}

QUALITY_DIMENSION_TO_DB: dict[QualityDimension, DbQualityDimension] = {
    QualityDimension.accuracy: DbQualityDimension.ACCURACY,
    QualityDimension.completeness: DbQualityDimension.COMPLETENESS,
    QualityDimension.consistency: DbQualityDimension.CONSISTENCY,
    QualityDimension.recency: DbQualityDimension.RECENCY,
    QualityDimension.timeliness: DbQualityDimension.TIMELINESS,
    QualityDimension.uniqueness: DbQualityDimension.UNIQUENESS,
    QualityDimension.validity: DbQualityDimension.VALIDITY,
}
QUALITY_DIMENSION_FROM_DB: dict[DbQualityDimension, QualityDimension] = {
    v: k for k, v in QUALITY_DIMENSION_TO_DB.items()
}
