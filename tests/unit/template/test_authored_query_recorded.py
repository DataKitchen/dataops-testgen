"""A test type whose query a user writes records the query its run sent.

The query is the test. Two runs of one definition send different SQL when one of them gives a
variable a value of its own, so a result that recorded only its thresholds would not say which
query produced its measure. ``{INPUT_PARAMETERS}`` carries the query as it ran, among the rest of
the parameters the test was set up with.

Which types record it follows from ``default_parm_columns``: a type that declares ``custom_query``
takes the query from the user, and one that does not builds its own and would write a fingerprint
or a measure expression into every result. CAT types build their result rows in Python rather than
from a template, and are covered by the unit tests over ``_get_input_parameters``.
"""

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

TEST_TYPE_DIR = Path(__file__).parents[3] / "testgen" / "template" / "dbsetup_test_types"

RECORDS_PARAMETERS = re.compile(r"^.*\bas input_parameters\b.*$", re.IGNORECASE | re.MULTILINE)

# The packaged types that take their query from the user. Table_Freshness is here because its
# fingerprint expression is a declared, required parameter a user can write and lock, even though
# test generation fills it; Freshness_Trend and Volume_Trend build theirs and declare nothing.
DECLARE_A_QUERY = {"CUSTOM", "Condition_Flag", "Metric_Trend", "SQL_Metric", "Table_Freshness"}


def _packaged_types() -> list[tuple[str, dict]]:
    return [
        (path.name, yaml.safe_load(path.read_text())["test_types"])
        for path in sorted(TEST_TYPE_DIR.glob("test_types_*.yaml"))
    ]


def _declares_a_query(test_type: dict) -> bool:
    return "custom_query" in (test_type.get("default_parm_columns") or "").split(",")


def test_the_packaged_test_types_were_found():
    """An empty list would pass every check below without reading anything."""
    assert _packaged_types()


def test_the_types_that_take_their_query_from_the_user_are_these():
    """Declaring the column is what makes a result record the query, so a type gaining or losing
    the declaration changes what every one of its results carries."""
    declaring = {
        test_type["test_type"] for _, test_type in _packaged_types() if _declares_a_query(test_type)
    }

    assert declaring == DECLARE_A_QUERY


@pytest.mark.parametrize("name, test_type", _packaged_types(), ids=lambda value: value if isinstance(value, str) else "")
def test_every_template_of_an_authored_query_records_the_query(name, test_type):
    if not _declares_a_query(test_type):
        pytest.skip("builds its own query, which describes the type rather than the test")

    recorded = [
        (template["sql_flavor"], line)
        for template in test_type.get("test_templates") or []
        for line in RECORDS_PARAMETERS.findall(template["template"])
    ]
    if not recorded:
        pytest.skip("builds its result rows in Python rather than from a template")

    for flavor, line in recorded:
        assert "{INPUT_PARAMETERS}" in line, (
            f"{name} ({flavor}) records input parameters without {{INPUT_PARAMETERS}}, so the "
            "query the run sent is lost: " + line.strip()
        )
