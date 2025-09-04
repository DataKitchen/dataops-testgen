import pytest

from testgen.commands.queries.profiling_query import CProfilingSQL


@pytest.mark.unit
def test_include_exclude_mask_basic():
    # test configuration
    project_code = "dummy_project_code"
    flavor = "postgresql"
    profiling_query = CProfilingSQL(project_code, flavor)
    profiling_query.parm_table_set = ""
    profiling_query.parm_table_include_mask = "important%, %useful%"
    profiling_query.parm_table_exclude_mask = "temp%,tmp%,raw_slot_utilization%,gps_product_step_change_log"

    # test run
    query, _ = profiling_query.GetDDFQuery()

    # test assertions
    assert "SELECT 'dummy_project_code'" in query
    assert r"""AND (
                (c.table_name LIKE 'important%' ) OR (c.table_name LIKE '%useful%' )
            )""" in query
    assert r"""AND NOT (
                (c.table_name LIKE 'temp%' ) OR (c.table_name LIKE 'tmp%' ) OR (c.table_name LIKE 'raw\_slot\_utilization%' ) OR (c.table_name LIKE 'gps\_product\_step\_change\_log' )
            )""" in query


@pytest.mark.unit
@pytest.mark.parametrize("mask", ("", None))
def test_include_empty_exclude_mask(mask):
    # test configuration
    project_code = "dummy_project_code"
    flavor = "snowflake"
    profiling_query = CProfilingSQL(project_code, flavor)
    profiling_query.parm_table_set = ""
    profiling_query.parm_table_include_mask = mask
    profiling_query.parm_table_exclude_mask = "temp%,tmp%,raw_slot_utilization%,gps_product_step_change_log"

    # test run
    query, _ = profiling_query.GetDDFQuery()
    print(query)

    # test assertions
    assert r"""AND NOT (
                (c.table_name LIKE 'temp%' ESCAPE '\\') OR (c.table_name LIKE 'tmp%' ESCAPE '\\') OR (c.table_name LIKE 'raw\\_slot\\_utilization%' ESCAPE '\\') OR (c.table_name LIKE 'gps\\_product\\_step\\_change\\_log' ESCAPE '\\')
            )""" in query


@pytest.mark.unit
@pytest.mark.parametrize("mask", ("", None))
def test_include_empty_include_mask(mask):
    # test configuration
    project_code = "dummy_project_code"
    flavor = "mssql"
    profiling_query = CProfilingSQL(project_code, flavor)
    profiling_query.parm_table_set = ""
    profiling_query.parm_table_include_mask = "important%, %useful_%"
    profiling_query.parm_table_exclude_mask = mask

    # test run
    query, _ = profiling_query.GetDDFQuery()
    print(query)

    # test assertions
    assert r"""AND (
                (c.table_name LIKE 'important%' ) OR (c.table_name LIKE '%useful[_]%' )
            )""" in query
