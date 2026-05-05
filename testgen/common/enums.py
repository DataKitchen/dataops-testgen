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
