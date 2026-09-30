"""Tests for the shared flavor-identity source of truth."""

import pathlib
import re

import pytest

from testgen.common.flavors import (
    FLAVOR_CODE_TO_FAMILY,
    FLAVOR_CODE_TO_LABEL,
    FLAVOR_FAMILIES,
    FLAVOR_TABLE_GROUP_SCHEMA_LABEL,
    SqlFlavorLabel,
    reports_table_group_schema,
    table_group_schema_label,
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


# --- Connection.effective_max_threads ---------------------------------------


@pytest.mark.parametrize(
    ("flavor", "code", "stored", "expected"),
    [
        # The pin wins over a stored column that disagrees with it.
        ("duckdb", "files", 4, 1),
        ("duckdb", "duckdb", 8, 1),
        ("postgresql", "postgresql", 6, 6),
        ("postgresql", "postgresql", None, 4),
    ],
)
def test_effective_max_threads_applies_the_flavor_pin(flavor, code, stored, expected):
    from testgen.common.models.connection import Connection

    connection = Connection(sql_flavor=flavor, sql_flavor_code=code, max_threads=stored)
    assert connection.effective_max_threads == expected


def test_every_target_fan_out_reads_the_pinned_thread_count():
    """A pin only holds where the fan-out reads it, and the stored column can disagree with it.

    A call site reverted to the column passes every other unit test: the pool of one absorbs the
    extra workers by serializing them, until one waits past the timeout and the run fails.
    """
    commands = pathlib.Path(__file__).resolve().parents[3] / "testgen" / "commands"
    offenders = [
        f"{path.relative_to(commands)}:{number}: {line.strip()}"
        for path in sorted(commands.rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if re.search(r"\.max_threads\b", line) and "effective_max_threads" not in line
    ]
    assert not offenders, "Read Connection.effective_max_threads instead:\n" + "\n".join(offenders)


# --- Table group schema label -----------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("files", None),
        ("s3", None),
        ("azure_blob", None),
        ("salesforce_data360", "Data Space"),
        ("duckdb", "Schema"),
        ("postgresql", "Schema"),
        ("snowflake", "Schema"),
        (None, "Schema"),
        ("a_code_that_does_not_exist", "Schema"),
    ],
)
def test_table_group_schema_label_names_the_value_per_flavor_code(code, expected):
    assert table_group_schema_label(code) == expected
    assert reports_table_group_schema(code) is (expected is not None)


def test_the_schema_label_registry_only_names_known_flavor_codes():
    assert set(FLAVOR_TABLE_GROUP_SCHEMA_LABEL) <= set(FLAVOR_CODE_TO_FAMILY)


def test_the_two_duckdb_codes_are_named_differently():
    """The codes share an engine family, so a label resolved from the family cannot tell them apart."""
    assert FLAVOR_CODE_TO_FAMILY["files"] == FLAVOR_CODE_TO_FAMILY["duckdb"]
    assert table_group_schema_label("files") != table_group_schema_label("duckdb")
