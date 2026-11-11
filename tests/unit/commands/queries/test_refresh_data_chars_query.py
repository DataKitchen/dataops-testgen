from datetime import UTC, datetime
from uuid import uuid4

import duckdb
import pytest

from testgen.commands.queries.refresh_data_chars_query import RefreshDataCharsSQL
from testgen.common.database.column_chars import ColumnChars
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup

pytestmark = pytest.mark.unit


def _make_columns(*table_names: str) -> list[ColumnChars]:
    return [
        ColumnChars(schema_name="default", table_name=name, column_name="id")
        for name in table_names
    ]


@pytest.mark.parametrize(
    "flavor,expected_sql",
    [
        ("bigquery", "SELECT  1 FROM `test_schema`.`orders` LIMIT 1"),
        ("databricks", "SELECT  1 FROM `test_schema`.`orders` LIMIT 1"),
        ("mssql", 'SELECT TOP 1 1 FROM "test_schema"."orders"'),
        ("postgresql", 'SELECT  1 FROM "test_schema"."orders" LIMIT 1'),
        ("redshift", 'SELECT  1 FROM "test_schema"."orders" LIMIT 1'),
        ("redshift_spectrum", 'SELECT  1 FROM "test_schema"."orders" LIMIT 1'),
        ("snowflake", 'SELECT  1 FROM "test_schema"."orders" LIMIT 1'),
        ("oracle", 'SELECT  1 FROM "test_schema"."orders" FETCH FIRST 1 ROWS ONLY'),
        ("sap_hana", 'SELECT  1 FROM "test_schema"."orders" LIMIT 1'),
        # Data 360 exposes DLOs unqualified — no schema prefix.
        ("salesforce_data360", 'SELECT  1 FROM "orders" LIMIT 1'),
    ],
)
def test_verify_access_uses_literal_1_projection(flavor, expected_sql):
    """Access check uses literal ``1`` (not ``*``) — projection doesn't matter for an
    existence/permission probe, and ``1`` avoids materialising columns on wide tables.

    Covers every flavor: the probe is the only thing standing behind the preview's
    Read Access column, and a probe that is invalid SQL on some flavor reports every
    table there as inaccessible."""
    connection = Connection(sql_flavor=flavor)
    table_group = TableGroup(table_group_schema="test_schema")
    sql_generator = RefreshDataCharsSQL(connection, table_group)

    query, _ = sql_generator.verify_access("orders")

    assert query == expected_sql


def test_include_exclude_mask_basic():
    connection = Connection(sql_flavor="postgresql")
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="",
        profiling_include_mask="important%, %useful%",
        profiling_exclude_mask="temp%,tmp%,raw_slot_utilization%,gps_product_step_change_log"
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    query, _ = sql_generator.get_schema_ddf()

    assert "WHERE c.table_schema = 'test_schema'" in query
    assert r"""AND (
                (c.table_name LIKE 'important%' ) OR (c.table_name LIKE '%useful%' )
            )""" in query
    assert r"""AND NOT (
                (c.table_name LIKE 'temp%' ) OR (c.table_name LIKE 'tmp%' ) OR (c.table_name LIKE 'raw\_slot\_utilization%' ) OR (c.table_name LIKE 'gps\_product\_step\_change\_log' )
            )""" in query


@pytest.mark.parametrize("mask", ("", None))
def test_include_empty_exclude_mask(mask):
    connection = Connection(sql_flavor="snowflake")
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="",
        profiling_include_mask=mask,
        profiling_exclude_mask="temp%,tmp%,raw_slot_utilization%,gps_product_step_change_log"
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    query, _ = sql_generator.get_schema_ddf()

    assert r"""AND NOT (
                (c.table_name LIKE 'temp%' ESCAPE '\\') OR (c.table_name LIKE 'tmp%' ESCAPE '\\') OR (c.table_name LIKE 'raw\\_slot\\_utilization%' ESCAPE '\\') OR (c.table_name LIKE 'gps\\_product\\_step\\_change\\_log' ESCAPE '\\')
            )""" in query


@pytest.mark.parametrize("mask", ("", None))
def test_include_empty_include_mask(mask):
    connection = Connection(sql_flavor="mssql")
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="",
        profiling_include_mask="important%, %useful_%",
        profiling_exclude_mask=mask,
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    query, _ = sql_generator.get_schema_ddf()

    assert r"""AND (
                (c.table_name LIKE N'important%' ) OR (c.table_name LIKE N'%useful[_]%' )
            )""" in query


@pytest.mark.parametrize("flavor,expected_predicate", [
    ("bigquery", r"(c.table_name LIKE 'raw\\_slot%' )"),
    ("sap_hana", r"(c.table_name LIKE 'raw\_slot%' ESCAPE '\')"),
])
def test_an_underscore_in_a_mask_matches_only_itself(flavor, expected_predicate):
    connection = Connection(sql_flavor=flavor)
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="",
        profiling_include_mask="raw_slot%",
        profiling_exclude_mask="",
    )
    query, _ = RefreshDataCharsSQL(connection, table_group).get_schema_ddf()

    assert expected_predicate in query


def test_table_set_only():
    connection = Connection(sql_flavor="postgresql")
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="users, orders, products",
        profiling_include_mask="",
        profiling_exclude_mask="",
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    criteria = sql_generator._get_table_criteria()

    assert "AND (c.table_name IN ('users', 'orders', 'products'))" in criteria
    assert "LIKE" not in criteria


@pytest.mark.parametrize("include", ("", None))
@pytest.mark.parametrize("exclude", ("", None))
def test_no_filters(include, exclude):
    connection = Connection(sql_flavor="postgresql")
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="",
        profiling_include_mask=include,
        profiling_exclude_mask=exclude,
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    criteria = sql_generator._get_table_criteria()

    assert criteria == ""


def test_table_set_with_include_exclude():
    connection = Connection(sql_flavor="postgresql")
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="users, orders",
        profiling_include_mask="important%",
        profiling_exclude_mask="temp%",
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    criteria = sql_generator._get_table_criteria()

    assert "AND (c.table_name IN ('users', 'orders'))" in criteria
    assert "LIKE 'important%'" in criteria
    assert "AND NOT" in criteria
    assert "LIKE 'temp%'" in criteria


def test_filter_schema_columns_table_set():
    connection = Connection(sql_flavor="salesforce_data360")
    table_group = TableGroup(
        table_group_schema="default",
        profiling_table_set="users, orders",
        profiling_include_mask="",
        profiling_exclude_mask="",
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    columns = _make_columns("users", "orders", "products", "logs")

    filtered = sql_generator.filter_schema_columns(columns)

    assert {c.table_name for c in filtered} == {"users", "orders"}


def test_filter_schema_columns_include_mask():
    connection = Connection(sql_flavor="salesforce_data360")
    table_group = TableGroup(
        table_group_schema="default",
        profiling_table_set="",
        profiling_include_mask="party_%, summary",
        profiling_exclude_mask="",
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    columns = _make_columns("party_planners", "party_transactions", "summary", "audit_log")

    filtered = sql_generator.filter_schema_columns(columns)

    assert {c.table_name for c in filtered} == {"party_planners", "party_transactions", "summary"}


def test_filter_schema_columns_exclude_mask():
    connection = Connection(sql_flavor="salesforce_data360")
    table_group = TableGroup(
        table_group_schema="default",
        profiling_table_set="",
        profiling_include_mask="",
        profiling_exclude_mask="tmp_%, raw_log",
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    columns = _make_columns("users", "tmp_x", "tmp_y", "raw_log", "orders")

    filtered = sql_generator.filter_schema_columns(columns)

    assert {c.table_name for c in filtered} == {"users", "orders"}


def test_filter_schema_columns_underscore_is_literal():
    # SQL LIKE _ wildcard semantics: the existing SQL path escapes user `_` to `\_`,
    # treating `_` as a literal. The Python filter must match that behavior.
    connection = Connection(sql_flavor="salesforce_data360")
    table_group = TableGroup(
        table_group_schema="default",
        profiling_table_set="",
        profiling_include_mask="a_b",
        profiling_exclude_mask="",
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    columns = _make_columns("a_b", "axb", "axxb")

    filtered = sql_generator.filter_schema_columns(columns)

    assert {c.table_name for c in filtered} == {"a_b"}


def test_filter_schema_columns_escaped_underscore_is_literal():
    connection = Connection(sql_flavor="salesforce_data360")
    table_group = TableGroup(
        table_group_schema="default",
        profiling_table_set="",
        profiling_include_mask=r"a\_%",
        profiling_exclude_mask="",
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    columns = _make_columns("a_b", "axb", r"a\_b")

    filtered = sql_generator.filter_schema_columns(columns)

    assert {c.table_name for c in filtered} == {"a_b"}


def test_filter_schema_columns_no_filters_returns_all():
    connection = Connection(sql_flavor="salesforce_data360")
    table_group = TableGroup(
        table_group_schema="default",
        profiling_table_set="",
        profiling_include_mask="",
        profiling_exclude_mask="",
    )
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    columns = _make_columns("users", "orders")

    filtered = sql_generator.filter_schema_columns(columns)

    assert {c.table_name for c in filtered} == {"users", "orders"}


def test_get_row_counts_handles_null_max_query_chars():
    """A connection with NULL max_query_chars must not crash chunking — it falls
    back to DEFAULT_MAX_QUERY_CHARS so the UNION ALL count queries still build."""
    connection = Connection(sql_flavor="postgresql", max_query_chars=None)
    table_group = TableGroup(table_group_schema="test_schema")
    sql_generator = RefreshDataCharsSQL(connection, table_group)

    result = sql_generator.get_row_counts(["orders", "customers"])

    assert result
    assert all(isinstance(query, str) and query for query, _ in result)


@pytest.mark.parametrize("mask", (",", " , ", ",,"))
def test_a_criterion_of_only_separators_applies_no_filter(mask):
    """A mask of only commas is a truthy string with no parts. The guards branch on the
    parts, so this applies no criterion rather than emitting an empty ``AND ( )``."""
    connection = Connection(sql_flavor="postgresql")
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="",
        profiling_include_mask=mask,
        profiling_exclude_mask=mask,
    )

    criteria = RefreshDataCharsSQL(connection, table_group)._get_table_criteria()

    assert criteria == ""


def test_trailing_comma_does_not_emit_an_empty_pattern():
    connection = Connection(sql_flavor="postgresql")
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="users,",
        profiling_include_mask="important%,",
        profiling_exclude_mask="",
    )

    criteria = RefreshDataCharsSQL(connection, table_group)._get_table_criteria()

    assert "IN ('users')" in criteria
    assert "LIKE ''" not in criteria
    assert "''" not in criteria.replace("IN ('users')", "")


def test_staging_rows_carry_the_file_count():
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor="duckdb"), TableGroup(table_group_schema="main"))
    column = ColumnChars(schema_name="main", table_name="claims", column_name="id", file_ct=3)

    [row] = sql_generator.get_staging_data_chars([column], datetime.now(UTC), uuid4())

    assert len(row) == len(sql_generator.staging_columns)
    assert row[sql_generator.staging_columns.index("file_ct")] == 3


def test_a_database_flavor_has_no_file_counts():
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor="postgresql"), TableGroup(table_group_schema="public"))

    assert sql_generator.get_file_counts() == []


def _two_declaration_counts(tmp_path, **kwargs) -> list[tuple[str, None]]:
    connection = Connection(sql_flavor="duckdb", sql_flavor_code="files", parameters={"base_path": str(tmp_path)})
    table_group = TableGroup(
        table_group_schema="main",
        file_declarations=[
            {"name": "claims", "uri": "claims_*.csv", "format": "csv"},
            {"name": "orders", "uri": "orders.csv", "format": "csv"},
        ],
    )
    return RefreshDataCharsSQL(connection, table_group).get_file_counts(**kwargs)


def test_each_declaration_is_counted_in_its_own_query(tmp_path):
    """A declaration whose files cannot be listed then fails only its own count."""
    queries = _two_declaration_counts(tmp_path)

    assert [params for _, params in queries] == [None, None]
    assert ["'claims' AS table_name" in query for query, _ in queries] == [True, False]
    assert ["'orders' AS table_name" in query for query, _ in queries] == [False, True]
    assert not any(" UNION ALL " in query for query, _ in queries)


def test_a_declaration_named_in_skip_is_not_counted(tmp_path):
    [(query, _)] = _two_declaration_counts(tmp_path, skip={"claims"})

    assert "'orders' AS table_name" in query


# --- schema resolution ---


def test_every_read_of_the_scanned_schema_agrees():
    """The scanned schema reaches the DDF query, the row counts and the access probe.

    A refresh that scans one schema while probing another would catalog rows the run cannot
    read, so all three have to agree.
    """
    connection = Connection(sql_flavor="postgresql", max_query_chars=10_000)
    sql_generator = RefreshDataCharsSQL(connection, TableGroup(table_group_schema="onboard_2026_09_10"))

    ddf_query, ddf_params = sql_generator.get_schema_ddf()
    assert ddf_params["DATA_SCHEMA"] == "onboard_2026_09_10"

    (count_query, _), = sql_generator.get_row_counts(["orders"])
    assert '"onboard_2026_09_10"."orders"' in count_query

    access_query, _ = sql_generator.verify_access("orders")
    assert '"onboard_2026_09_10"."orders"' in access_query


def test_the_catalog_merge_disables_nested_loops_before_its_first_write():
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor="postgresql"), TableGroup(table_group_schema="public"))

    merge_sql, _ = sql_generator.update_data_chars(datetime.now(UTC), uuid4())[0]
    statements = [
        "\n".join(line for line in statement.splitlines() if not line.strip().startswith("--")).strip()
        for statement in merge_sql.split(";")
    ]
    first_write = next(index for index, statement in enumerate(statements) if statement.startswith("WITH"))

    assert "SET LOCAL enable_nestloop = off" in statements[:first_write]


def test_the_catalog_merge_joins_each_updated_column_to_its_alias_by_primary_key():
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor="postgresql"), TableGroup(table_group_schema="public"))

    merge_sql, _ = sql_generator.update_data_chars(datetime.now(UTC), uuid4())[0]
    column_updates = [statement for statement in merge_sql.split(";") if "UPDATE data_column_chars" in statement]

    assert len(column_updates) == 2
    for statement in column_updates:
        assert "WHERE data_column_chars.column_id = d.column_id" in statement
        assert "data_column_chars.column_name" not in statement


@pytest.mark.parametrize("include_mask,exclude_mask", [("sales_%", "sales_tmp%"), (r"sales\_%", r"sales\_tmp%")])
def test_duckdb_mask_underscore_matches_only_a_literal_underscore(include_mask, exclude_mask):
    """DuckDB's LIKE has no default escape character, so the escaped underscore needs an ESCAPE clause."""
    table_group = TableGroup(
        table_group_schema="main",
        profiling_table_set="",
        profiling_include_mask=include_mask,
        profiling_exclude_mask=exclude_mask,
    )
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor="duckdb"), table_group)
    column = sql_generator.flavor_service.ddf_table_ref
    names = ["sales_orders", "salesXorders", "sales_tmp_load", "other"]

    rows = duckdb.connect().sql(
        f"SELECT {column} FROM (VALUES {', '.join(f"('{name}')" for name in names)}) AS c({column})"
        f" WHERE TRUE {sql_generator._get_table_criteria()}"
    ).fetchall()

    assert rows == [("sales_orders",)]


@pytest.mark.parametrize(
    "flavor,expected_clause",
    [
        ("postgresql", r"(c.table_name LIKE 'sales\_%' )"),
        ("redshift", r"(c.table_name LIKE 'sales\\_%' )"),
        ("snowflake", r"(c.table_name LIKE 'sales\\_%' ESCAPE '\\')"),
        ("oracle", r"(c.table_name LIKE 'sales\_%' ESCAPE '\')"),
        ("mssql", "(c.table_name LIKE N'sales[_]%' )"),
        ("duckdb", r"(c.table_name LIKE 'sales\_%' ESCAPE '\')"),
        ("sap_hana", r"(c.table_name LIKE 'sales\_%' ESCAPE '\')"),
        ("bigquery", r"(c.table_name LIKE 'sales\\_%' )"),
        ("databricks", r"(c.table_name LIKE 'sales\\_%' )"),
    ],
)
@pytest.mark.parametrize("mask", ["sales_%", r"sales\_%"])
def test_mask_underscore_is_escaped_for_each_flavor(flavor, expected_clause, mask):
    table_group = TableGroup(table_group_schema="test_schema", profiling_include_mask=mask)
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor=flavor), table_group)

    assert expected_clause in sql_generator._get_table_criteria()


@pytest.mark.parametrize(
    "flavor,expected_clause",
    [
        ("postgresql", r"(c.table_name LIKE 'tmp\\' )"),
        ("redshift", r"(c.table_name LIKE 'tmp\\\\' )"),
        ("redshift_spectrum", r"(c.tablename LIKE 'tmp\\\\' )"),
        ("snowflake", r"(c.table_name LIKE 'tmp\\\\' ESCAPE '\\')"),
        ("oracle", r"(c.table_name LIKE 'tmp\\' ESCAPE '\')"),
        ("mssql", r"(c.table_name LIKE N'tmp\' )"),
        ("duckdb", r"(c.table_name LIKE 'tmp\\' ESCAPE '\')"),
        ("sap_hana", r"(c.table_name LIKE 'tmp\\' ESCAPE '\')"),
        ("bigquery", r"(c.table_name LIKE 'tmp\\\\' )"),
        ("databricks", r"(c.table_name LIKE 'tmp\\\\' )"),
    ],
)
def test_mask_backslash_is_escaped_for_each_flavor(flavor, expected_clause):
    table_group = TableGroup(table_group_schema="test_schema", profiling_include_mask="tmp\\")
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor=flavor), table_group)

    assert expected_clause in sql_generator._get_table_criteria()


@pytest.mark.parametrize("flavor,expected_clause", [
    ("mssql", "(c.table_name LIKE N'[[]x]%' )"),
    ("postgresql", "(c.table_name LIKE '[x]%' )"),
])
def test_mask_left_bracket_is_literal_on_sql_server_only(flavor, expected_clause):
    table_group = TableGroup(table_group_schema="test_schema", profiling_include_mask="[x]%")
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor=flavor), table_group)

    assert expected_clause in sql_generator._get_table_criteria()


@pytest.mark.parametrize(
    "include_mask,expected",
    [
        ("tmp\\", ["tmp\\"]),
        (r"a\b%", [r"a\b", r"a\bc"]),
        (r"a\%", [r"a\b", r"a\bc", "a\\"]),
        (r"a\_b", ["a_b"]),
    ],
)
def test_duckdb_mask_backslash_matches_only_a_literal_backslash(include_mask, expected):
    table_group = TableGroup(table_group_schema="main", profiling_table_set="", profiling_include_mask=include_mask)
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor="duckdb"), table_group)
    column = sql_generator.flavor_service.ddf_table_ref
    names = ["tmp\\", "tmp", r"a\b", r"a\bc", "ab", "a\\", "a_b", "a%b"]
    values = ", ".join(f"('{name}')" for name in names)

    rows = duckdb.connect().sql(
        f"SELECT {column} FROM (VALUES {values}) AS c({column}) WHERE TRUE {sql_generator._get_table_criteria()}"
        f" ORDER BY {column}"
    ).fetchall()

    assert [row[0] for row in rows] == sorted(expected)


@pytest.mark.parametrize(
    "include_mask,expected",
    [("tmp\\", {"tmp\\"}), (r"a\b%", {r"a\b", r"a\bc"}), (r"a\%", {r"a\b", r"a\bc", "a\\"})],
)
def test_filter_schema_columns_backslash_is_literal(include_mask, expected):
    table_group = TableGroup(table_group_schema="default", profiling_table_set="", profiling_include_mask=include_mask)
    sql_generator = RefreshDataCharsSQL(Connection(sql_flavor="salesforce_data360"), table_group)
    columns = _make_columns("tmp\\", "tmp", r"a\b", r"a\bc", "ab", "a\\")

    assert {c.table_name for c in sql_generator.filter_schema_columns(columns)} == expected


@pytest.mark.parametrize(
    "flavor,expected_name,expected_mask",
    [
        ("postgresql", "'o''brien'", "'o''brien%'"),
        ("bigquery", r"'o\'brien'", r"'o\'brien%'"),
    ],
)
def test_single_quote_in_table_criteria_is_escaped(flavor, expected_name, expected_mask):
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="o'brien",
        profiling_include_mask="o'brien%",
    )
    criteria = RefreshDataCharsSQL(Connection(sql_flavor=flavor), table_group)._get_table_criteria()

    assert f"IN ({expected_name})" in criteria
    assert f"LIKE {expected_mask}" in criteria


@pytest.mark.parametrize(
    "flavor,expected_mask",
    [("snowflake", r"LIKE 'x\\\\'' OR 1=1) --'"), ("bigquery", r"LIKE 'x\\\\\' OR 1=1) --'")],
)
def test_trailing_backslash_cannot_end_the_literal(flavor, expected_mask):
    table_group = TableGroup(
        table_group_schema="test_schema",
        profiling_table_set="orders\\",
        profiling_include_mask="x\\' OR 1=1) --",
    )
    criteria = RefreshDataCharsSQL(Connection(sql_flavor=flavor), table_group)._get_table_criteria()

    assert r"IN ('orders\\')" in criteria
    assert expected_mask in criteria


def test_table_set_is_split_into_in_lists_of_at_most_1000():
    table_names = [f"t{i}" for i in range(2001)]
    table_group = TableGroup(table_group_schema="test_schema", profiling_table_set=",".join(table_names))

    criteria = RefreshDataCharsSQL(Connection(sql_flavor="oracle"), table_group)._get_table_criteria()

    in_lists = criteria.split(" OR ")
    assert len(in_lists) == 3
    assert [in_list.count("'") // 2 for in_list in in_lists] == [1000, 1000, 1]


def test_an_explicit_table_set_is_split_into_in_lists_of_at_most_1000():
    """The tables a run reads are named outright, and there can be more of them than Oracle takes
    in one IN list."""
    table_group = TableGroup(table_group_schema="test_schema")
    table_names = [f"t{i:04d}" for i in range(2001)]

    criteria = RefreshDataCharsSQL(
        Connection(sql_flavor="oracle"), table_group, table_names=table_names
    )._get_table_criteria()

    in_lists = criteria.split(" OR ")
    assert len(in_lists) == 3
    assert [in_list.count("'") // 2 for in_list in in_lists] == [1000, 1000, 1]


def test_no_tables_to_read_matches_nothing():
    table_group = TableGroup(table_group_schema="test_schema")

    criteria = RefreshDataCharsSQL(
        Connection(sql_flavor="postgresql"), table_group, table_names=[]
    )._get_table_criteria()

    assert criteria == " AND 1=0"
