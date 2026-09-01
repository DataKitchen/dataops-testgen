"""Guards tying the job_executions DDL to the lifecycle declared in Python."""

import re
from pathlib import Path

import pytest

import testgen
from testgen.common.enums import JobStatus
from testgen.common.models.job_execution import JobExecution

pytestmark = pytest.mark.unit

TEMPLATE_ROOT = Path(testgen.__file__).parent / "template"
POLL_INDEX = re.compile(
    r"CREATE INDEX idx_job_executions_poll.*?WHERE status IN \(([^)]*)\)",
    re.DOTALL,
)
# Both forms that set the status column's width: the table's own DDL and a later widening.
STATUS_WIDTH = re.compile(
    r"status\s+VARCHAR\((\d+)\)\s+NOT NULL DEFAULT 'pending'"
    r"|ALTER TABLE job_executions\s+ALTER COLUMN status TYPE VARCHAR\((\d+)\)",
    re.DOTALL,
)


def _effective_poll_index_predicates() -> dict[str, set[str]]:
    """The status set the poll index ends up filtering on, per install path.

    A merged migration is immutable, so earlier ones legitimately hold earlier predicates --
    what a live database ends up with is whatever the highest-numbered one declares.
    """
    def predicate_in(sql_path: Path) -> set[str] | None:
        matches = POLL_INDEX.findall(sql_path.read_text(encoding="utf-8"))
        if not matches:
            return None
        return {value.strip().strip("'") for value in matches[-1].split(",")}

    upgrades = sorted((TEMPLATE_ROOT / "dbupgrade").glob("*.sql"))
    latest_upgrade = next(
        (path for path in reversed(upgrades) if predicate_in(path) is not None), None
    )
    return {
        "fresh install": predicate_in(TEMPLATE_ROOT / "dbsetup" / "030_initialize_new_schema_structure.sql"),
        f"upgrade ({latest_upgrade.name})": predicate_in(latest_upgrade),
    }


def test_the_poll_index_predicate_matches_the_claim_query():
    """A partial index is only usable for a query whose filter it covers, so a predicate that
    drifts from ACTIONABLE_STATUSES costs the poll its index scan -- silently, with no error."""
    expected = {status.value for status in JobExecution.ACTIONABLE_STATUSES}
    for install_path, predicate in _effective_poll_index_predicates().items():
        assert predicate == expected, install_path


def _effective_status_widths() -> dict[str, int]:
    """The width the status column ends up with, per install path."""
    def width_in(sql_path: Path) -> int | None:
        matches = STATUS_WIDTH.findall(sql_path.read_text(encoding="utf-8"))
        if not matches:
            return None
        return int(next(group for group in matches[-1] if group))

    upgrades = sorted((TEMPLATE_ROOT / "dbupgrade").glob("*.sql"))
    latest_upgrade = next((path for path in reversed(upgrades) if width_in(path) is not None), None)
    return {
        "fresh install": width_in(TEMPLATE_ROOT / "dbsetup" / "030_initialize_new_schema_structure.sql"),
        f"upgrade ({latest_upgrade.name})": width_in(latest_upgrade),
    }


def test_the_status_column_fits_every_status_on_every_install_path():
    """A value longer than the column fails at runtime, on that transition only -- and a widening
    applied to one install path and not the other leaves the two schemas disagreeing."""
    widths = _effective_status_widths()
    longest = max(len(status.value) for status in JobStatus)
    for install_path, width in widths.items():
        assert width >= longest, install_path
    assert len(set(widths.values())) == 1, widths
