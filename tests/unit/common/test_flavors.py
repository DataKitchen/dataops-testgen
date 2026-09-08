"""Tests for the shared flavor-identity source of truth."""

import re

import pytest

from testgen.common.flavors import (
    FLAVOR_CODE_TO_FAMILY,
    FLAVOR_CODE_TO_LABEL,
    FLAVOR_FAMILIES,
    SqlFlavorLabel,
)
from testgen.common.read_file import read_template_sql_file

pytestmark = pytest.mark.unit


def test_label_and_family_maps_cover_the_same_codes():
    assert set(FLAVOR_CODE_TO_LABEL) == set(FLAVOR_CODE_TO_FAMILY)


def test_every_label_is_a_known_enum_member():
    assert set(FLAVOR_CODE_TO_LABEL.values()) == set(SqlFlavorLabel)


def test_labels_are_unique_per_code():
    labels = list(FLAVOR_CODE_TO_LABEL.values())
    assert len(labels) == len(set(labels))


def test_azure_variants_share_the_mssql_family():
    assert FLAVOR_CODE_TO_FAMILY["azure_mssql"] == "mssql"
    assert FLAVOR_CODE_TO_FAMILY["synapse_mssql"] == "mssql"
    assert FLAVOR_CODE_TO_FAMILY["mssql"] == "mssql"


def test_label_renders_as_plain_string():
    assert f"{FLAVOR_CODE_TO_LABEL['postgresql']}" == "PostgreSQL"
    assert str(FLAVOR_CODE_TO_LABEL["azure_mssql"]) == "Azure SQL Database"


# --- fn_quote_literal_escape covers every family ------------------------------------------

def _quote_literal_escape_branches(source: str) -> list[frozenset[str]]:
    """The flavor names each branch of the function's IF/ELSIF chain matches on, in order."""
    body = source[source.index("fn_quote_literal_escape"):]
    body = body[:body.index("RAISE EXCEPTION")]
    conditions = re.findall(r"lower_case_sql_flavor (?:=|IN)\s*(\(?[^T]*?)\s*THEN", body)
    return [frozenset(re.findall(r"'([a-z_0-9]+)'", condition)) for condition in conditions]


def _quote_literal_escape_flavors(source: str) -> set[str]:
    """Every flavor name the function matches on, across all branches."""
    return {name for branch in _quote_literal_escape_branches(source) for name in branch}


@pytest.mark.parametrize(
    ("template", "directory"),
    [
        ("020_create_standard_functions_sprocs.sql", "dbsetup"),
        ("0222_incremental_upgrade.sql", "dbupgrade"),
    ],
)
def test_quote_literal_escape_handles_every_flavor_family(template, directory):
    """The function raises for an unlisted flavor, and only when a constant column of the right
    type is selected — so an omission surfaces as a broken test run on one flavor rather than in
    CI. This is the cheap gate on that.

    The upgrade copy is checked too: 020 is not among the scripts the upgrade path re-runs, so the
    two have to stay in step.
    """
    named = _quote_literal_escape_flavors(read_template_sql_file(template, directory))
    assert FLAVOR_FAMILIES <= named, f"not handled: {sorted(FLAVOR_FAMILIES - named)}"


def test_the_two_quote_literal_escape_copies_group_the_flavors_identically():
    """The migration repeats the function because the upgrade path never re-runs dbsetup/020.

    Comparing only the set of names each copy mentions would let them drift over which branch a
    flavor lands in — the thing that decides how its literals are escaped — and stay green.
    """
    from testgen.common.read_file import read_template_sql_file

    setup = _quote_literal_escape_branches(
        read_template_sql_file("020_create_standard_functions_sprocs.sql", "dbsetup")
    )
    migration = _quote_literal_escape_branches(
        read_template_sql_file("0222_incremental_upgrade.sql", "dbupgrade")
    )
    assert setup == migration
