"""Generated test definitions name the table group's schema, not a profiled row's.

Generation reads ``profile_results``, and those rows keep the schema they were profiled against.
A table group that has since moved would therefore mint definitions naming where its data used to
be -- on the ordinary path, with no override anywhere -- and every one of them would look for
tables in a schema the table group no longer uses.

``:DATA_SCHEMA`` is bound from the table group itself, so taking the inserted value from there is
what keeps generation and the table group in step.
"""

import re
from pathlib import Path

import pytest

import testgen

pytestmark = pytest.mark.unit

TEMPLATE_ROOT = Path(testgen.__file__).parent / "template"

# The value landing in the INSERT's column list, as its own line.
ROW_SOURCED = re.compile(r"^\s+[a-z]+\.schema_name,\s*$", re.MULTILINE)


def _generation_templates() -> list[Path]:
    return sorted(p for p in TEMPLATE_ROOT.rglob("*.sql") if "INSERT INTO test_definitions" in p.read_text())


def test_generation_templates_exist():
    """Guards the guard: a path change that finds nothing would pass every assertion below."""
    assert len(_generation_templates()) > 20


@pytest.mark.parametrize("path", _generation_templates(), ids=lambda p: p.name)
def test_inserts_the_table_groups_schema(path):
    text = path.read_text()

    assert not ROW_SOURCED.search(text), (
        f"{path.name} inserts a schema read off a row. Profiling rows keep the schema they ran "
        "against, so a table group reading another one generates tests naming a schema it does "
        "not read. Use :DATA_SCHEMA."
    )
    if "profile_results" in text:
        # Seeding templates insert literals and have no row to read a schema off; only the ones
        # generating from a profiling run have to be told which schema to name.
        assert ":DATA_SCHEMA" in text, f"{path.name} generates from profiling without naming a schema"
