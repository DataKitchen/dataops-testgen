"""A test type template reading the data catalog matches the table group's own table name.

The catalog always describes the table group, whatever location a run reads, so a template that
matched the catalog on ``{TABLE_NAME}`` would find nothing the moment a run overrode its tables
and would report a false failure. ``{CATALOG_TABLE_NAME}`` carries the definition's name.
"""

import glob
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

CATALOG_TABLES = ("data_column_chars", "data_table_chars")
# `<alias.>table_name = '{TABLE_NAME}'`, the shape a catalog lookup takes.
MATCHES_ON_TABLE_NAME = re.compile(r"\b(?:\w+\.)?table_name\s*=\s*'\{TABLE_NAME\}'")


def _test_type_yaml() -> list[str]:
    return sorted(glob.glob("testgen/testgen/template/dbsetup_test_types/test_types_*.yaml"))


def test_the_packaged_test_types_were_found():
    """The glob is relative to the repo root, so an empty list means the suite ran elsewhere and
    every check below would pass without reading anything."""
    assert _test_type_yaml()


@pytest.mark.parametrize("path", _test_type_yaml(), ids=lambda p: Path(p).stem)
def test_a_catalog_lookup_matches_the_definition_s_table(path):
    text = Path(path).read_text()
    if not any(table in text for table in CATALOG_TABLES):
        pytest.skip("reads the target, not the catalog")

    assert not MATCHES_ON_TABLE_NAME.search(text), (
        f"{Path(path).name} matches the data catalog on {{TABLE_NAME}}, which is the location the "
        "run reads. Use {CATALOG_TABLE_NAME}, the name the test definition carries."
    )
