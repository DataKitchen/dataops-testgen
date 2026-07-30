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
        ("trino", 'SELECT  1 FROM "test_schema"."orders" LIMIT 1'),
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
                (c.table_name LIKE 'important%' ) OR (c.table_name LIKE '%useful[_]%' )
            )""" in query


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

    assert "IN ('users','orders','products')" in criteria
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

    assert "IN ('users','orders')" in criteria
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
