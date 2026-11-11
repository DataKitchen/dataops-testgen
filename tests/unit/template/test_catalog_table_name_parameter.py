"""A test type template reading the application's own records matches the definition's table name.

The data catalog and a contract's declared schema both describe the table group, whatever location
a run reads, so a template matching one of them on ``{TABLE_NAME}`` would find nothing the moment a
run overrode its tables and would report a false failure. ``{CATALOG_TABLE_NAME}`` carries the name
the test definition is defined on.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TEST_TYPE_DIR = Path(__file__).parents[3] / "testgen" / "template" / "dbsetup_test_types"

# Application tables that hold the table group's own records rather than the target's data.
TABLE_GROUP_SCOPED = ("data_column_chars", "data_table_chars", "suite_versions")
# Any comparison against the run's read location, whichever expression is on the left: a bare
# column, a qualified one, or the COALESCE a contract's declared name is read through.
MATCHES_ON_TABLE_NAME = re.compile(r"=\s*'\{TABLE_NAME\}'")


def _test_type_yaml() -> list[Path]:
    return sorted(TEST_TYPE_DIR.glob("test_types_*.yaml"))


def test_the_packaged_test_types_were_found():
    """An empty list would pass every check below without reading anything."""
    assert _test_type_yaml()


@pytest.mark.parametrize("path", _test_type_yaml(), ids=lambda p: p.stem)
def test_a_table_group_scoped_lookup_matches_the_definition_s_table(path):
    text = path.read_text()
    if not any(table in text for table in TABLE_GROUP_SCOPED):
        pytest.skip("reads the target, not the application's own records")

    assert not MATCHES_ON_TABLE_NAME.search(text), (
        f"{path.name} matches the application's own records on {{TABLE_NAME}}, which is the "
        "location the run reads. Use {CATALOG_TABLE_NAME}, the name the test definition carries."
    )
