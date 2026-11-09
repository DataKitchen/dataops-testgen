"""Tests for the shared flavor-identity source of truth."""

import pathlib
import re
from types import SimpleNamespace

import pytest

from testgen.common.clean_sql import NonNumericValueError
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import get_flavor_service
from testgen.common.flavors import (
    FLAVOR_CODE_TO_FAMILY,
    FLAVOR_CODE_TO_LABEL,
    FLAVOR_FAMILIES,
    FLAVOR_FIXED_MAX_THREADS,
    FLAVOR_TABLE_GROUP_SCHEMA_LABEL,
    IN_PROCESS_FLAVOR_CODES,
    SqlFlavorCode,
    SqlFlavorLabel,
    clamp_max_threads,
    default_max_threads,
    recommended_max_threads,
    reports_table_group_schema,
    runs_in_process,
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


# --- FlavorService.string_literal agrees with fn_quote_literal_escape ------------------------

# What each branch of the function produces for a value holding a quote and a backslash, as the
# literal its flavors read back as ``a'b\c``.
_BRANCH_LITERALS = ["'a''b\\c'", "'a''b\\\\c'", "'a''b\\c'", "'a\\'b\\\\c'"]


@pytest.mark.parametrize("family", sorted(FLAVOR_FAMILIES))
def test_string_literal_escapes_like_fn_quote_literal_escape(family):
    branches = _quote_literal_escape_branches(
        read_template_sql_file("020_create_standard_functions_sprocs.sql", "dbsetup")
    )
    assert len(branches) == len(_BRANCH_LITERALS)
    branch = next(index for index, names in enumerate(branches) if family in names)
    service = get_flavor_service(family)
    literal = service.string_literal("a'b\\c")
    assert literal.removeprefix(service.string_literal_prefix) == _BRANCH_LITERALS[branch]


def test_mssql_string_literal_is_national():
    assert get_flavor_service("mssql").string_literal("café") == "N'café'"


def test_string_literal_or_null_renders_null_when_empty():
    service = get_flavor_service("postgresql")
    assert service.string_literal_or_null("") == "NULL"
    assert service.string_literal_or_null(None) == "NULL"
    assert service.string_literal_or_null("it's") == "'it''s'"


def test_string_literal_list_renders_null_when_empty():
    assert get_flavor_service("postgresql").string_literal_list([]) == "NULL"


def test_string_literal_list_keeps_empty_and_comma_values():
    assert get_flavor_service("postgresql").string_literal_list(["", "a,b", " "]) == "'', 'a,b', ' '"


# --- FlavorService.value_list_params ---------------------------------------


def _column(general_type: str, column_type: str | None = None) -> ColumnChars:
    return ColumnChars("s", "t", "c", general_type=general_type, column_type=column_type)


def test_value_list_params_matches_a_numeric_column_by_value():
    params = get_flavor_service("postgresql").value_list_params('"c"', _column("N"), ["1", "2.50", "1.0", "1e2"])
    assert params == {
        "VALUE_LIST_COLUMN": '"c"',
        "VALUE_LIST_DISTINCT": '"c"',
        "VALUE_LIST_LITERALS": "1, 2.50, 100",
        "VALUE_LIST_CT": "3",
        "VALUE_LIST_VALUE": '"c"',
        "VALUE_LIST_ROWS": "SELECT 1 AS expected_value, 1 AS value_key"
        " UNION ALL SELECT 2.50 AS expected_value, 2.50 AS value_key"
        " UNION ALL SELECT 100 AS expected_value, 100 AS value_key",
    }


def test_value_list_params_writes_exact_numbers_on_bigquery():
    params = get_flavor_service("bigquery").value_list_params("`c`", _column("N"), ["1", "0.1234567890123"])
    assert params["VALUE_LIST_LITERALS"] == "BIGNUMERIC '1', BIGNUMERIC '0.1234567890123'"
    assert params["VALUE_LIST_ROWS"] == (
        "SELECT BIGNUMERIC '1' AS expected_value, BIGNUMERIC '1' AS value_key"
        " UNION ALL SELECT BIGNUMERIC '0.1234567890123' AS expected_value, BIGNUMERIC '0.1234567890123' AS value_key"
    )


def test_value_list_params_rejects_a_non_numeric_value_for_a_numeric_column():
    with pytest.raises(NonNumericValueError):
        get_flavor_service("postgresql").value_list_params('"c"', _column("N"), ["1", "1); DROP TABLE t; --"])


@pytest.mark.parametrize("column", [_column("A"), _column("D"), None])
def test_value_list_params_matches_other_columns_exactly_by_text(column):
    params = get_flavor_service("postgresql").value_list_params('"c"', column, ["a", "A", "a", "it's", ""])
    assert params["VALUE_LIST_COLUMN"] == 'CAST("c" AS VARCHAR(1000)) COLLATE "C"'
    assert params["VALUE_LIST_DISTINCT"] == params["VALUE_LIST_COLUMN"]
    assert params["VALUE_LIST_VALUE"] == 'CAST("c" AS VARCHAR(1000))'
    assert params["VALUE_LIST_LITERALS"] == "'a' COLLATE \"C\", 'A' COLLATE \"C\", 'it''s' COLLATE \"C\", '' COLLATE \"C\""
    assert params["VALUE_LIST_CT"] == "4"


@pytest.mark.parametrize("family", sorted(FLAVOR_FAMILIES))
def test_value_list_params_compares_column_and_literals_in_one_form(family):
    service = get_flavor_service(family)
    params = service.value_list_params('"c"', _column("A"), ["x"])
    assert params["VALUE_LIST_COLUMN"] == service.exact_text(service.value_list_text('"c"'))
    assert params["VALUE_LIST_LITERALS"] == service.exact_text(service.string_literal("x"))


def test_value_list_params_compares_bytes_on_mssql():
    params = get_flavor_service("mssql").value_list_params('"c"', _column("A", "char(5)"), ["é "])
    assert params["VALUE_LIST_COLUMN"] == 'CAST(CAST(RTRIM("c") AS NVARCHAR(MAX)) AS VARBINARY(MAX))'
    assert params["VALUE_LIST_LITERALS"] == "CAST(N'é ' AS VARBINARY(MAX))"


def test_value_list_params_compares_bytes_on_redshift():
    params = get_flavor_service("redshift").value_list_params('"c"', _column("A"), ["a "])
    assert params["VALUE_LIST_COLUMN"] == "TO_VARBYTE(CAST(\"c\" AS VARCHAR(1000)), 'utf8')"
    assert params["VALUE_LIST_LITERALS"] == "TO_VARBYTE('a ', 'utf8')"


def test_value_list_params_reads_char_without_its_padding_on_oracle():
    column = _column("A", "char(5)")
    column.db_data_type = "CHAR(5)"
    params = get_flavor_service("oracle").value_list_params('"c"', column, ["a"])
    assert params["VALUE_LIST_COLUMN"] == "NLSSORT(CAST(RTRIM(\"c\") AS VARCHAR2(1000)), 'NLS_SORT=BINARY')"


def test_value_list_params_leaves_out_the_empty_string_on_oracle():
    params = get_flavor_service("oracle").value_list_params('"c"', _column("A"), ["", "a"])
    assert params["VALUE_LIST_CT"] == "1"
    assert params["VALUE_LIST_LITERALS"] == "NLSSORT('a', 'NLS_SORT=BINARY')"
    assert params["VALUE_LIST_ROWS"] == (
        "SELECT 'a' AS expected_value, NLSSORT('a', 'NLS_SORT=BINARY') AS value_key FROM DUAL"
    )


def test_value_list_params_selects_rows_from_dummy_on_sap_hana():
    params = get_flavor_service("sap_hana").value_list_params('"c"', _column("N"), ["1", "2"])
    assert params["VALUE_LIST_ROWS"] == (
        "SELECT 1 AS expected_value, 1 AS value_key FROM DUMMY"
        " UNION ALL SELECT 2 AS expected_value, 2 AS value_key FROM DUMMY"
    )


def test_value_list_params_renders_an_empty_list_as_matching_nothing():
    params = get_flavor_service("oracle").value_list_params('"c"', _column("A"), [])
    assert params["VALUE_LIST_LITERALS"] == "NULL"
    assert params["VALUE_LIST_CT"] == "0"
    assert params["VALUE_LIST_ROWS"] == "SELECT NULL AS expected_value, NULL AS value_key FROM DUAL WHERE 1 = 0"


# --- Connection.effective_max_threads ---------------------------------------


@pytest.mark.parametrize(
    ("flavor", "code", "stored", "expected"),
    [
        # The pin wins over a stored column that disagrees with it.
        ("duckdb", "files", 4, 1),
        ("duckdb", "duckdb", 8, 1),
        ("postgresql", "postgresql", 6, 6),
        # A stored value outside the range a user can choose is cut to it.
        ("snowflake", "snowflake", 40, 16),
        ("snowflake", "snowflake", 0, 1),
    ],
)
def test_effective_max_threads_applies_the_flavor_pin(flavor, code, stored, expected):
    from testgen.common.models.connection import Connection

    connection = Connection(sql_flavor=flavor, sql_flavor_code=code, max_threads=stored)
    assert connection.effective_max_threads == expected


@pytest.mark.parametrize(
    ("code", "recommended", "default"),
    [
        ("mssql", 2, 2),
        ("azure_mssql", 2, 2),
        ("redshift", 2, 2),
        ("oracle", 2, 2),
        ("bigquery", 8, 8),
        ("synapse_mssql", None, 4),
        ("onelake_mssql", None, 4),
        ("redshift_spectrum", None, 4),
        ("snowflake", None, 4),
        ("duckdb", None, 1),
        ("files", None, 1),
        (None, None, 4),
    ],
)
def test_default_max_threads_per_flavor(code, recommended, default):
    assert recommended_max_threads(code) == recommended
    assert default_max_threads(code) == default


@pytest.mark.parametrize(("value", "expected"), [(-3, 1), (0, 1), (1, 1), (16, 16), (17, 16)])
def test_clamp_max_threads_cuts_to_the_choosable_range(value, expected):
    assert clamp_max_threads(value) == expected


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"sql_flavor": "mssql", "sql_flavor_code": "mssql"}, 2),
        ({"sql_flavor": "bigquery", "sql_flavor_code": "bigquery"}, 8),
        ({"sql_flavor": "redshift", "sql_flavor_code": None}, 2),
        ({"sql_flavor": "postgresql", "sql_flavor_code": "postgresql"}, 4),
        ({"sql_flavor": "duckdb", "sql_flavor_code": "s3"}, 1),
    ],
)
def test_a_new_connection_without_a_thread_count_stores_its_flavor_default(params, expected):
    from testgen.common.models.connection import Connection

    context = SimpleNamespace(get_current_parameters=lambda: params)
    assert Connection.__table__.c.max_threads.default.arg(context) == expected


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


def test_every_in_process_flavor_and_only_those_fix_the_thread_count():
    assert set(FLAVOR_FIXED_MAX_THREADS) == IN_PROCESS_FLAVOR_CODES
    assert set(FLAVOR_FIXED_MAX_THREADS.values()) == {1}


def test_in_process_flavors_are_the_duckdb_family():
    assert {code for code, family in FLAVOR_CODE_TO_FAMILY.items() if family == "duckdb"} == IN_PROCESS_FLAVOR_CODES


@pytest.mark.parametrize(
    ("code", "expected"),
    [(SqlFlavorCode.DUCKDB, True), (SqlFlavorCode.AZURE_BLOB, True), (SqlFlavorCode.SNOWFLAKE, False), (None, False)],
)
def test_runs_in_process(code, expected):
    assert runs_in_process(code) is expected
