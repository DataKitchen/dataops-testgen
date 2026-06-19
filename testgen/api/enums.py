"""Lowercase presentation enums for API v1 request filters and responses.

Shared home for StrEnums that map a DB-stored value to the lowercase snake_case
form exposed through the API. Several DB columns store title-case values
(``test_results.result_status``, ``*.disposition``); the mapping dicts here are the
single seam that normalizes them to the API surface — the DB is never changed.
"""

from enum import StrEnum

from testgen.common.enums import Disposition as DbDisposition
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
