"""Every template that writes a table group's catalog takes the table group's lock first.

The catalog refresh and the score rollups update the same catalog rows in different orders, so
two of them running at once on one table group deadlock unless they queue on a shared lock.
"""

import re
from pathlib import Path

import pytest

import testgen

pytestmark = pytest.mark.unit

TEMPLATE_ROOT = Path(testgen.__file__).parent / "template"

# The schema scripts and the quick-start seed run once, before any job can write the catalog.
EXCLUDED_DIRS = ("dbsetup", "dbupgrade", "quick_start")

CATALOG_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:TABLE_GROUPS_ID AS VARCHAR), 0))"

_WRITES_CATALOG = re.compile(
    r"\b(UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+data_(column|table)_chars\b", re.IGNORECASE
)


def _statements(sql: str) -> list[str]:
    without_comments = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


def _catalog_writers() -> list[Path]:
    return [
        sql_path
        for sql_path in TEMPLATE_ROOT.rglob("*.sql")
        if not any(part in EXCLUDED_DIRS for part in sql_path.relative_to(TEMPLATE_ROOT).parts)
        and _WRITES_CATALOG.search(sql_path.read_text())
    ]


def test_catalog_writer_templates_exist():
    # Guards the scan itself: an empty list would make the next test vacuously pass.
    assert len(_catalog_writers()) >= 8


def test_every_catalog_writer_template_takes_the_table_group_lock_first():
    offenders = sorted(
        str(path.relative_to(TEMPLATE_ROOT))
        for path in _catalog_writers()
        if _statements(path.read_text())[0] != CATALOG_LOCK
    )

    assert offenders == [], (
        "a template that writes data_column_chars or data_table_chars without first taking the "
        "table group's lock can deadlock with the other catalog writers. Offenders: " + ", ".join(offenders)
    )
