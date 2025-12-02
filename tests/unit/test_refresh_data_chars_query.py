import pytest

from testgen.commands.queries.refresh_data_chars_query import RefreshDataCharsSQL
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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
