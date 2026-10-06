"""Required and Required_No_Placeholder split the columns Required would select on its own."""

import itertools
from pathlib import Path

import duckdb
import pytest
import yaml

import testgen

pytestmark = pytest.mark.unit

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"
NO_NULLS = "record_ct = value_ct AND record_ct > 10"


def _criteria(test_type: str) -> str:
    return yaml.safe_load((YAML_DIR / f"test_types_{test_type}.yaml").read_text())["test_types"]["selection_criteria"]


def test_required_and_required_no_placeholder_partition_the_no_null_columns():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE profile_results (general_type VARCHAR, record_ct INT, value_ct INT, "
        "zero_length_ct INT, filled_value_ct INT, sample_ratio DOUBLE)"
    )
    # Non-text columns carry NULL text counts, so NULL is one of the cases
    rows = itertools.product(["A", "N", "D", None], [5, 20], [5, 19, 20], [None, 0, 1], [None, 0, 2], [None, 2.5])
    con.executemany("INSERT INTO profile_results VALUES (?, ?, ?, ?, ?, ?)", list(rows))

    def selected(criteria: str) -> set[tuple]:
        return set(con.execute(f"SELECT * FROM profile_results WHERE {criteria}").fetchall())

    required = selected(_criteria("Required"))
    no_placeholder = selected(_criteria("Required_No_Placeholder"))

    assert no_placeholder
    # A sampled profile counts empty strings and placeholders on the sample, which can miss them
    assert all(row[-1] is None for row in no_placeholder)
    assert not required & no_placeholder
    assert required | no_placeholder == selected(NO_NULLS)
