from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.mcp.exceptions import MCPUserError

# -- list_tests ---------------------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_tests_basic(mock_td, mock_notes, db_session_mock):
    suite_id = str(uuid4())
    item = MagicMock()
    item.test_type = "Alpha_Trunc"
    item.test_name_short = "Alpha Truncation"
    item.table_name = "orders"
    item.column_name = "customer_name"
    item.test_active = True
    item.severity = "Warning"
    item.default_severity = None
    item.threshold_value = "10.0"
    item.lock_refresh = True
    item.last_auto_gen_date = "2026-04-01"
    item.flagged = True
    item.id = uuid4()
    mock_td.list_for_suite.return_value = ([item], 1)
    mock_notes.get_notes_count_by_ids.return_value = {str(item.id): 2}

    from testgen.mcp.tools.test_definitions import list_tests

    result = list_tests(suite_id)

    assert "Alpha Truncation" in result
    assert "`orders`" in result
    assert "`customer_name`" in result
    assert "Warning" in result
    assert "Locked" in result  # header
    assert "Manual" in result  # header
    mock_td.list_for_suite.assert_called_once()
    call_kwargs = mock_td.list_for_suite.call_args
    assert call_kwargs.kwargs["test_suite_id"] is not None
    assert call_kwargs.kwargs["page"] == 1
    assert call_kwargs.kwargs["limit"] == 50


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_tests_empty(mock_td, db_session_mock):
    suite_id = str(uuid4())
    mock_td.list_for_suite.return_value = ([], 0)

    from testgen.mcp.tools.test_definitions import list_tests

    result = list_tests(suite_id)

    assert "No test definitions found" in result
    assert suite_id in result


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_tests_empty_with_filters(mock_td, db_session_mock):
    suite_id = str(uuid4())
    mock_td.list_for_suite.return_value = ([], 0)

    from testgen.mcp.tools.test_definitions import list_tests

    result = list_tests(suite_id, table_name="orders")

    assert "No test definitions found" in result
    assert "table=orders" in result


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_tests_empty_page_beyond(mock_td, db_session_mock):
    suite_id = str(uuid4())
    mock_td.list_for_suite.return_value = ([], 5)

    from testgen.mcp.tools.test_definitions import list_tests

    result = list_tests(suite_id, page=3)

    assert "No tests on page 3" in result
    assert "total: 5" in result


@patch("testgen.mcp.tools.common.TestType")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_tests_with_test_type_filter(mock_td, mock_tt, mock_tt_common, db_session_mock):
    suite_id = str(uuid4())
    mock_td.list_for_suite.return_value = ([], 0)

    tt = MagicMock()
    tt.test_type = "Alpha_Trunc"
    tt.test_name_short = "Alpha Truncation"
    mock_tt_common.select_where.return_value = [tt]

    from testgen.mcp.tools.test_definitions import list_tests

    result = list_tests(suite_id, test_type="Alpha Truncation")

    call_kwargs = mock_td.list_for_suite.call_args.kwargs
    assert call_kwargs["test_type"] == "Alpha_Trunc"


def test_list_tests_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_definitions import list_tests

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        list_tests("not-a-uuid")


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_tests_passes_project_codes(mock_td, db_session_mock):
    suite_id = str(uuid4())
    mock_td.list_for_suite.return_value = ([], 0)

    from testgen.mcp.tools.test_definitions import list_tests

    list_tests(suite_id)

    call_kwargs = mock_td.list_for_suite.call_args.kwargs
    assert call_kwargs["project_codes"] == ["demo"]


# -- get_test -----------------------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestResult")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_basic(mock_td, mock_tr, mock_notes, db_session_mock):
    td_id = uuid4()
    td = MagicMock()
    td.id = td_id
    td.test_type = "Alpha_Trunc"
    td.test_name_short = "Alpha Truncation"
    td.dq_dimension = "Accuracy"
    td.table_name = "orders"
    td.column_name = "customer_name"
    td.schema_name = "public"
    td.test_scope = "column"
    td.test_suite_id = uuid4()
    td.test_active = True
    td.severity = "Warning"
    td.default_severity = None
    td.lock_refresh = False
    td.export_to_observability = True
    td.measure_uom = "Values over max"
    td.flagged = False
    td.last_auto_gen_date = None
    td.last_manual_update = None
    td.default_parm_columns = None
    td.custom_query = None
    td.match_schema_name = None
    td.match_table_name = None
    td.match_column_names = None
    td.match_subset_condition = None
    td.match_groupby_names = None
    td.match_having_condition = None
    td.test_description = None
    td.default_test_description = "Checks for truncated alpha values"
    td.usage_notes = None
    mock_td.get_for_project.return_value = td
    mock_notes.get_notes.return_value = []

    mock_tr.select_history.return_value = []

    from testgen.mcp.tools.test_definitions import get_test

    result = get_test(str(td_id))

    assert "Alpha Truncation" in result
    assert "`customer_name`" in result
    assert "`orders`" in result
    assert "Accuracy" in result
    assert "Checks for truncated alpha values" in result
    assert "No results recorded" in result
    assert "Not Flagged, No Notes" in result


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_not_found(mock_td, db_session_mock):
    td_id = str(uuid4())
    mock_td.get_for_project.return_value = None

    from testgen.mcp.tools.test_definitions import get_test

    result = get_test(td_id)

    assert "not found" in result


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestResult")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_with_last_result(mock_td, mock_tr, mock_notes, db_session_mock):
    td_id = uuid4()

    td = MagicMock()
    td.id = td_id
    td.test_type = "Row_Ct"
    td.test_name_short = "Row Count"
    td.dq_dimension = "Completeness"
    td.table_name = "orders"
    td.column_name = None
    td.schema_name = "public"
    td.test_scope = "table"
    td.test_suite_id = uuid4()
    td.test_active = True
    td.severity = None
    td.default_severity = "Fail"
    td.lock_refresh = False
    td.export_to_observability = False
    td.measure_uom = "Row count"
    td.flagged = False
    td.last_auto_gen_date = None
    td.last_manual_update = None
    td.default_parm_columns = None
    td.custom_query = None
    td.match_schema_name = None
    td.match_table_name = None
    td.match_column_names = None
    td.match_subset_condition = None
    td.match_groupby_names = None
    td.match_having_condition = None
    td.test_description = None
    td.default_test_description = None
    td.usage_notes = None
    mock_td.get_for_project.return_value = td
    mock_notes.get_notes.return_value = []

    last = MagicMock()
    last.test_time = "2026-04-01 12:00:00"
    last.status = MagicMock(value="Failed")
    last.result_measure = "0"
    last.threshold_value = "100"
    last.message = "Table is empty"
    mock_tr.select_history.return_value = [last]

    from testgen.mcp.tools.test_definitions import get_test

    result = get_test(str(td_id))

    assert "Row Count" in result
    assert "2026-04-01" in result
    assert "Failed" in result
    assert "Table is empty" in result


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestResult")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_with_parameters(mock_td, mock_tr, mock_notes, db_session_mock):
    td_id = uuid4()

    td = MagicMock()
    td.id = td_id
    td.test_type = "Alpha_Trunc"
    td.test_name_short = "Alpha Truncation"
    td.dq_dimension = None
    td.table_name = "orders"
    td.column_name = "name"
    td.schema_name = "public"
    td.test_scope = "column"
    td.test_suite_id = uuid4()
    td.test_active = True
    td.severity = None
    td.default_severity = None
    td.lock_refresh = False
    td.export_to_observability = False
    td.measure_uom = None
    td.flagged = False
    td.last_auto_gen_date = None
    td.last_manual_update = None
    td.default_parm_columns = "threshold_value,baseline_value"
    td.default_parm_prompts = "Threshold,Baseline"
    td.default_parm_help = "Max allowed value|Reference baseline"
    td.threshold_value = "5.0"
    td.baseline_value = "3.0"
    td.custom_query = None
    td.match_schema_name = None
    td.match_table_name = None
    td.match_column_names = None
    td.match_subset_condition = None
    td.match_groupby_names = None
    td.match_having_condition = None
    td.test_description = None
    td.default_test_description = None
    td.usage_notes = None
    mock_td.get_for_project.return_value = td
    mock_notes.get_notes.return_value = []

    mock_tr.select_history.return_value = []

    from testgen.mcp.tools.test_definitions import get_test

    result = get_test(str(td_id))

    assert "Parameters" in result
    assert "Threshold" in result
    assert "Baseline" in result
    assert "5.0" in result


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestResult")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_flagged_with_notes(mock_td, mock_tr, mock_notes, db_session_mock):
    from datetime import datetime

    td_id = uuid4()

    td = MagicMock()
    td.id = td_id
    td.test_type = "Alpha_Trunc"
    td.test_name_short = "Alpha Truncation"
    td.dq_dimension = None
    td.table_name = "orders"
    td.column_name = "name"
    td.schema_name = "public"
    td.test_scope = "column"
    td.test_suite_id = uuid4()
    td.test_active = True
    td.severity = None
    td.default_severity = None
    td.lock_refresh = False
    td.export_to_observability = False
    td.measure_uom = None
    td.flagged = True
    td.last_auto_gen_date = datetime(2026, 3, 15)
    td.last_manual_update = None
    td.default_parm_columns = None
    td.custom_query = None
    td.match_schema_name = None
    td.match_table_name = None
    td.match_column_names = None
    td.match_subset_condition = None
    td.match_groupby_names = None
    td.match_having_condition = None
    td.test_description = None
    td.default_test_description = None
    td.usage_notes = None
    mock_td.get_for_project.return_value = td
    mock_notes.get_notes.return_value = [{"id": "1", "detail": "needs review"}, {"id": "2", "detail": "checked"}]

    mock_tr.select_history.return_value = []

    from testgen.mcp.tools.test_definitions import get_test

    result = get_test(str(td_id))

    assert "Flagged, 2 Notes" in result
    assert "auto-generated" in result
    assert "2026-03-15" in result


def test_get_test_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_definitions import get_test

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_test("garbage")


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_passes_project_codes(mock_td, db_session_mock):
    td_id = str(uuid4())
    mock_td.get_for_project.return_value = None

    from testgen.mcp.tools.test_definitions import get_test

    get_test(td_id)

    call_args = mock_td.get_for_project.call_args
    assert call_args.args[1] == ["demo"]


# -- list_test_notes ----------------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_test_notes_basic(mock_td, mock_notes, db_session_mock):
    td_id = str(uuid4())

    td = MagicMock()
    td.test_type = "Alpha_Trunc"
    td.test_name_short = "Alpha Truncation"
    td.table_name = "orders"
    td.column_name = "name"
    mock_td.get_for_project.return_value = td

    mock_notes.get_notes.return_value = [
        {"detail": "Threshold looks wrong", "created_by": "alice", "created_at": "2026-04-01T10:00:00", "updated_at": None},
        {"detail": "Confirmed with team", "created_by": "bob", "created_at": "2026-04-02T14:30:00", "updated_at": "2026-04-03T09:00:00"},
    ]

    from testgen.mcp.tools.test_definitions import list_test_notes

    result = list_test_notes(td_id)

    assert "Alpha Truncation" in result
    assert "`name`" in result
    assert "`orders`" in result
    assert "2 notes" in result
    assert "Threshold looks wrong" in result
    assert "alice" in result
    assert "2026-04-01 10:00" in result
    assert "2026-04-03 09:00" in result


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_test_notes_empty(mock_td, mock_notes, db_session_mock):
    td_id = str(uuid4())
    td = MagicMock()
    mock_td.get_for_project.return_value = td
    mock_notes.get_notes.return_value = []

    from testgen.mcp.tools.test_definitions import list_test_notes

    result = list_test_notes(td_id)

    assert "No notes" in result


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_test_notes_not_found(mock_td, db_session_mock):
    td_id = str(uuid4())
    mock_td.get_for_project.return_value = None

    from testgen.mcp.tools.test_definitions import list_test_notes

    result = list_test_notes(td_id)

    assert "not found" in result


def test_list_test_notes_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_definitions import list_test_notes

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        list_test_notes("garbage")


# -- list_test_types ----------------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.TestType")
def test_list_test_types_basic(mock_tt, db_session_mock):
    tt = MagicMock()
    tt.test_name_short = "Alpha Truncation"
    tt.dq_dimension = "Accuracy"
    tt.test_scope = "column"
    tt.test_description = "Checks for truncated values"
    mock_tt.select_where.return_value = [tt]

    from testgen.mcp.tools.test_definitions import list_test_types

    result = list_test_types()

    assert "Alpha Truncation" in result
    assert "Accuracy" in result
    assert "column" in result


@patch("testgen.mcp.tools.test_definitions.TestType")
def test_list_test_types_empty(mock_tt, db_session_mock):
    mock_tt.select_where.return_value = []

    from testgen.mcp.tools.test_definitions import list_test_types

    result = list_test_types()

    assert "No test types found" in result


@patch("testgen.mcp.tools.test_definitions.TestType")
def test_list_test_types_with_scope_filter(mock_tt, db_session_mock):
    mock_tt.select_where.return_value = []
    mock_tt.test_scope = "column"
    mock_tt.active = "Y"

    from testgen.mcp.tools.test_definitions import list_test_types

    result = list_test_types(scope="column")

    assert "No test types found" in result
    assert "scope=column" in result


def test_list_test_types_invalid_scope(db_session_mock):
    from testgen.mcp.tools.test_definitions import list_test_types

    with pytest.raises(MCPUserError, match="Invalid scope"):
        list_test_types(scope="invalid")


def test_list_test_types_invalid_quality_dimension(db_session_mock):
    from testgen.mcp.tools.test_definitions import list_test_types

    with pytest.raises(MCPUserError, match="Invalid quality_dimension"):
        list_test_types(quality_dimension="NotADimension")


@patch("testgen.mcp.tools.test_definitions.TestType")
def test_list_test_types_filter_description(mock_tt, db_session_mock):
    tt = MagicMock()
    tt.test_name_short = "Row Count"
    tt.dq_dimension = "Completeness"
    tt.test_scope = "table"
    tt.test_description = "Checks row count"
    mock_tt.select_where.return_value = [tt]

    from testgen.mcp.tools.test_definitions import list_test_types

    result = list_test_types(scope="table", quality_dimension="Completeness")

    assert "scope: table" in result
    assert "dimension: Completeness" in result
