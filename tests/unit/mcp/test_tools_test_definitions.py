from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.custom_test_validation import CustomQueryResult
from testgen.mcp.exceptions import MCPUserError

# -- list_tests ---------------------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_tests_basic(mock_td, mock_notes, db_session_mock):
    suite_id = str(uuid4())
    item = MagicMock()
    item.test_type = "Alpha_Trunc"
    item.test_name_short = "Alpha Truncation"
    item.display_name = "Alpha Truncation"
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
    td.display_name = "Alpha Truncation"
    td.impact_dimension = "Reliability"
    td.default_impact_dimension = "Conformance"
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
    td.param_columns = set()
    td.param_fields = []
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
    assert "Reliability" in result
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
    td.display_name = "Row Count"
    td.impact_dimension = None
    td.default_impact_dimension = "Conformance"
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
    td.param_columns = set()
    td.param_fields = []
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
    td.display_name = "Alpha Truncation"
    td.impact_dimension = None
    td.default_impact_dimension = "Conformance"
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
    td.param_columns = {"threshold_value", "baseline_value"}
    td.param_fields = [("threshold_value", "Threshold", ""), ("baseline_value", "Baseline", "")]
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
    td.display_name = "Alpha Truncation"
    td.impact_dimension = None
    td.default_impact_dimension = "Conformance"
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
    td.param_columns = set()
    td.param_fields = []
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
    td.display_name = "Alpha Truncation"
    td.table_name = "orders"
    td.column_name = "name"
    mock_td.get_for_project.return_value = td

    note_id_1 = str(uuid4())
    note_id_2 = str(uuid4())
    mock_notes.get_notes.return_value = [
        {"id": note_id_1, "detail": "Threshold looks wrong", "created_by": "alice", "created_at": "2026-04-01T10:00:00", "updated_at": None},
        {"id": note_id_2, "detail": "Confirmed with team", "created_by": "bob", "created_at": "2026-04-02T14:30:00", "updated_at": "2026-04-03T09:00:00"},
    ]

    from testgen.mcp.tools.test_definitions import list_test_notes

    result = list_test_notes(td_id)

    assert "Alpha Truncation" in result
    assert "`name`" in result
    assert "`orders`" in result
    assert "2 note(s)" in result
    assert "Threshold looks wrong" in result
    assert "alice" in result
    assert "2026-04-01 10:00" in result
    assert "2026-04-03 09:00" in result
    assert "Test note ID" in result
    assert note_id_1 in result
    assert note_id_2 in result


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


# -- create_test_note ---------------------------------------------------------


def _make_note_summary():
    """Minimal TestDefinitionSummary mock for note-tool rendering."""
    summary = MagicMock()
    summary.display_name = "Alpha Truncation"
    summary.table_name = "orders"
    summary.column_name = "email"
    return summary


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_create_test_note_happy_path(
    mock_resolve_td, mock_td, mock_note_model, mcp_user, db_session_mock,
):
    mcp_user.username = "test_user"
    td = MagicMock(id=uuid4())
    mock_resolve_td.return_value = td

    note_instance = MagicMock(
        id=uuid4(),
        detail="Threshold widened — confirmed with team",
        created_at="2026-05-27T10:00:00",
    )
    mock_note_model.add_note.return_value = note_instance
    mock_td.get_for_project.return_value = _make_note_summary()

    from testgen.mcp.tools.test_definitions import create_test_note

    result = create_test_note(str(td.id), "Threshold widened — confirmed with team")

    assert "Note added" in result
    assert "Alpha Truncation" in result
    assert "`email`" in result
    assert "`orders`" in result
    assert "test_user" in result
    assert str(note_instance.id) in result
    mock_note_model.add_note.assert_called_once_with(td.id, "Threshold widened — confirmed with team", "test_user")


@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_create_test_note_rejects_empty_body(mock_resolve_td, db_session_mock):
    from testgen.mcp.tools.test_definitions import create_test_note

    with pytest.raises(MCPUserError, match="cannot be empty"):
        create_test_note(str(uuid4()), "")
    with pytest.raises(MCPUserError, match="cannot be empty"):
        create_test_note(str(uuid4()), "   \n\t  ")

    mock_resolve_td.assert_not_called()


def test_create_test_note_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_definitions import create_test_note

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        create_test_note("garbage", "valid detail")


# -- update_test_note ---------------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.resolve_test_note")
def test_update_test_note_happy_path(
    mock_resolve_note, mock_td, mock_note_model, mcp_user, db_session_mock,
):
    mcp_user.username = "test_user"
    note = MagicMock(
        id=uuid4(),
        test_definition_id=uuid4(),
        created_by="test_user",
        detail="original body",
    )
    mock_resolve_note.return_value = note
    mock_td.get_for_project.return_value = _make_note_summary()

    from testgen.mcp.tools.test_definitions import update_test_note

    result = update_test_note(str(note.id), "rewritten body")

    assert "Note updated" in result
    assert "Alpha Truncation" in result
    assert "original body" in result
    assert "rewritten body" in result
    mock_note_model.update_note.assert_called_once_with(note.id, "rewritten body")


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.resolve_test_note")
def test_update_test_note_non_author_rejected(
    mock_resolve_note, mock_note_model, mcp_user, db_session_mock,
):
    mcp_user.username = "test_user"
    note = MagicMock(created_by="someone_else")
    mock_resolve_note.return_value = note

    from testgen.mcp.tools.test_definitions import update_test_note

    with pytest.raises(MCPUserError, match="You can only edit notes you authored"):
        update_test_note(str(uuid4()), "new body")

    mock_note_model.update_note.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.resolve_test_note")
def test_update_test_note_rejects_empty_body(mock_resolve_note, db_session_mock):
    from testgen.mcp.tools.test_definitions import update_test_note

    with pytest.raises(MCPUserError, match="cannot be empty"):
        update_test_note(str(uuid4()), "")
    with pytest.raises(MCPUserError, match="cannot be empty"):
        update_test_note(str(uuid4()), "   ")

    mock_resolve_note.assert_not_called()


def test_update_test_note_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_definitions import update_test_note

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        update_test_note("garbage", "valid detail")


# -- delete_test_note ---------------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.resolve_test_note")
def test_delete_test_note_happy_path(
    mock_resolve_note, mock_td, mock_note_model, mcp_user, db_session_mock,
):
    mcp_user.username = "test_user"
    note = MagicMock(
        id=uuid4(),
        test_definition_id=uuid4(),
        created_by="test_user",
        created_at="2026-05-27T10:00:00",
    )
    mock_resolve_note.return_value = note
    mock_td.get_for_project.return_value = _make_note_summary()

    from testgen.mcp.tools.test_definitions import delete_test_note

    result = delete_test_note(str(note.id))

    assert "Note deleted" in result
    assert "Alpha Truncation" in result
    assert "test_user" in result
    mock_note_model.delete_note.assert_called_once_with(note.id)


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.resolve_test_note")
def test_delete_test_note_non_author_rejected(
    mock_resolve_note, mock_note_model, mcp_user, db_session_mock,
):
    mcp_user.username = "test_user"
    note = MagicMock(created_by="someone_else")
    mock_resolve_note.return_value = note

    from testgen.mcp.tools.test_definitions import delete_test_note

    with pytest.raises(MCPUserError, match="You can only delete notes you authored"):
        delete_test_note(str(uuid4()))

    mock_note_model.delete_note.assert_not_called()


def test_delete_test_note_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.test_definitions import delete_test_note

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        delete_test_note("garbage")


# -- list_test_types ----------------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.TestType")
def test_list_test_types_basic(mock_tt, db_session_mock):
    tt = MagicMock()
    tt.test_name_short = "Alpha Truncation"
    tt.impact_dimension = "Conformance"
    tt.dq_dimension = "Accuracy"
    tt.test_scope = "column"
    tt.test_description = "Checks for truncated values"
    mock_tt.select_where.return_value = [tt]

    from testgen.mcp.tools.test_definitions import list_test_types

    result = list_test_types()

    assert "Alpha Truncation" in result
    assert "Conformance" in result
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
    tt.impact_dimension = "Regularity"
    tt.dq_dimension = "Completeness"
    tt.test_scope = "table"
    tt.test_description = "Checks row count"
    mock_tt.select_where.return_value = [tt]

    from testgen.mcp.tools.test_definitions import list_test_types

    result = list_test_types(scope="table", quality_dimension="Completeness")

    assert "scope: table" in result
    assert "dimension: Completeness" in result


# -- create_test --------------------------------------------------------------


def _make_suite(suite_id=None, table_groups_id=None):
    suite = MagicMock()
    suite.id = suite_id or uuid4()
    suite.test_suite = "demo_suite"
    suite.project_code = "demo"
    suite.table_groups_id = table_groups_id or uuid4()
    return suite


def _make_test_type(
    code="Alpha_Trunc",
    short_name="Alpha Truncation",
    scope="column",
    param_columns=None,
    default_parm_columns="threshold_value",
    default_parm_required=None,
    default_severity="Fail",
):
    tt = MagicMock()
    tt.test_type = code
    tt.test_name_short = short_name
    tt.test_scope = scope
    tt.param_columns = param_columns if param_columns is not None else {"threshold_value"}
    tt.default_parm_columns = default_parm_columns
    tt.default_parm_required = default_parm_required
    tt.default_severity = default_severity
    return tt


def _make_table_group(schema="public"):
    tg = MagicMock()
    tg.id = uuid4()
    tg.table_group_schema = schema
    return tg


def _make_td_summary(table_name="orders", column_name="email", severity="Warning"):
    """Mock TestDefinitionSummary as returned by TestDefinition.get_for_project()."""
    summary = MagicMock()
    summary.id = uuid4()
    summary.display_name = "Alpha Truncation"
    summary.test_type = "Alpha_Trunc"
    summary.test_name_short = "Alpha Truncation"
    summary.table_name = table_name
    summary.column_name = column_name
    summary.schema_name = "demo"
    summary.test_scope = "column"
    summary.test_suite_id = uuid4()
    summary.impact_dimension = None
    summary.default_impact_dimension = "Conformance"
    summary.dq_dimension = "Validity"
    summary.test_active = True
    summary.severity = severity
    summary.default_severity = "Fail"
    summary.lock_refresh = False
    summary.export_to_observability = True
    summary.flagged = False
    summary.last_auto_gen_date = None
    summary.last_manual_update = None
    summary.default_parm_columns = "threshold_value"
    summary.param_columns = {"threshold_value"}
    summary.param_fields = [("threshold_value", "Maximum String Length at Baseline", "")]
    summary.threshold_value = "64"
    summary.custom_query = None
    summary.match_schema_name = None
    summary.match_table_name = None
    summary.match_column_names = None
    summary.match_subset_condition = None
    summary.match_groupby_names = None
    summary.match_having_condition = None
    return summary


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_create_test_happy_path(
    mock_resolve_suite, mock_resolve_tt, mock_tt_model, mock_tg, mock_td, mock_notes, db_session_mock,
):
    suite = _make_suite()
    mock_resolve_suite.return_value = suite
    mock_resolve_tt.return_value = "Alpha_Trunc"
    mock_tt_model.get.return_value = _make_test_type()
    mock_tg.get.return_value = _make_table_group()

    saved = MagicMock()
    saved.id = uuid4()
    saved.editable_fields.return_value = {
        "test_active", "severity", "lock_refresh", "flagged", "test_description",
        "threshold_value", "column_name",
    }
    mock_td.return_value = saved
    mock_td.get_for_project.return_value = _make_td_summary()
    mock_notes.get_notes.return_value = []

    from testgen.mcp.tools.test_definitions import create_test

    result = create_test(
        test_suite_id=str(uuid4()),
        test_type="Alpha Truncation",
        table_name="orders",
        fields={"column_name": "email", "threshold_value": "64", "severity": "Warning"},
    )

    # New shared body: entity-first heading + "Created in suite" lead-in
    assert "Created" in result
    assert "Alpha Truncation on `email` in `orders`" in result
    # Parameters table uses the test type's prompt, not a hardcoded label
    assert "Maximum String Length at Baseline" in result
    assert "64" in result
    assert "Warning" in result
    saved.save.assert_called_once()


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_create_test_column_scope_requires_column_name(
    mock_resolve_suite, mock_resolve_tt, mock_tt_model, mock_tg, mock_td, db_session_mock,
):
    """Column-scoped types: missing column_name → validate() raises before save."""
    from testgen.common.models.test_definition import InvalidTestDefinitionFields

    mock_resolve_suite.return_value = _make_suite()
    mock_resolve_tt.return_value = "Alpha_Trunc"
    mock_tt_model.get.return_value = _make_test_type()
    mock_tg.get.return_value = _make_table_group()

    saved = MagicMock(id=uuid4())
    saved.editable_fields.return_value = {
        "test_active", "severity", "lock_refresh", "flagged", "test_description",
        "threshold_value", "column_name",
    }
    saved.validate.side_effect = InvalidTestDefinitionFields(
        {"column_name": "required for test type `Alpha_Trunc`"}
    )
    mock_td.return_value = saved

    from testgen.mcp.tools.test_definitions import create_test

    with pytest.raises(MCPUserError) as exc_info:
        create_test(
            test_suite_id=str(uuid4()),
            test_type="Alpha Truncation",
            table_name="orders",
            fields={"threshold_value": "64"},
        )
    assert "column_name" in str(exc_info.value)
    assert "rejected" in str(exc_info.value).lower()
    saved.save.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_create_test_unknown_field_rejected_by_whitelist(
    mock_resolve_suite, mock_resolve_tt, mock_tt_model, mock_tg, mock_td, db_session_mock,
):
    """Unknown field in ``fields`` (e.g. custom_query on Alpha_Trunc) is rejected by editable_fields whitelist."""
    mock_resolve_suite.return_value = _make_suite()
    mock_resolve_tt.return_value = "Alpha_Trunc"
    mock_tt_model.get.return_value = _make_test_type()
    mock_tg.get.return_value = _make_table_group()

    saved = MagicMock(id=uuid4())
    saved.editable_fields.return_value = {
        "test_active", "severity", "lock_refresh", "flagged", "test_description",
        "threshold_value", "column_name",
    }
    mock_td.return_value = saved

    from testgen.mcp.tools.test_definitions import create_test

    with pytest.raises(MCPUserError) as exc_info:
        create_test(
            test_suite_id=str(uuid4()),
            test_type="Alpha Truncation",
            table_name="orders",
            fields={"column_name": "email", "threshold_value": "64", "custom_query": "SELECT 1"},
        )
    assert "custom_query" in str(exc_info.value)
    assert "not editable" in str(exc_info.value)
    saved.save.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_create_test_fields_dict_supports_test_type_params(
    mock_resolve_suite, mock_resolve_tt, mock_tt_model, mock_tg, mock_td, mock_notes, db_session_mock,
):
    """``fields`` accepts any param in editable_fields — e.g. window_days for a trend test."""
    mock_resolve_suite.return_value = _make_suite()
    mock_resolve_tt.return_value = "Some_Trend"
    mock_tt_model.get.return_value = _make_test_type(
        code="Some_Trend",
        param_columns={"threshold_value", "window_days"},
        default_parm_columns="threshold_value,window_days",
    )
    mock_tg.get.return_value = _make_table_group()

    saved = MagicMock(id=uuid4())
    saved.editable_fields.return_value = {
        "test_active", "severity", "lock_refresh", "flagged", "test_description",
        "threshold_value", "window_days", "column_name",
    }
    mock_td.return_value = saved
    mock_td.get_for_project.return_value = _make_td_summary()
    mock_notes.get_notes.return_value = []

    from testgen.mcp.tools.test_definitions import create_test

    create_test(
        test_suite_id=str(uuid4()),
        test_type="Some Trend",
        table_name="orders",
        fields={"column_name": "amount", "threshold_value": "10", "window_days": "7"},
    )

    # Both common and type-specific fields applied via setattr
    assert saved.threshold_value == "10"
    assert saved.window_days == "7"
    saved.validate.assert_called_once()
    saved.save.assert_called_once()


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_create_test_severity_invalid(
    mock_resolve_suite, mock_resolve_tt, mock_tt_model, mock_tg, mock_td, db_session_mock,
):
    """severity outside the StrEnum → validate() raises."""
    from testgen.common.models.test_definition import InvalidTestDefinitionFields

    mock_resolve_suite.return_value = _make_suite()
    mock_resolve_tt.return_value = "Alpha_Trunc"
    mock_tt_model.get.return_value = _make_test_type()
    mock_tg.get.return_value = _make_table_group()

    saved = MagicMock(id=uuid4())
    saved.editable_fields.return_value = {
        "test_active", "severity", "lock_refresh", "flagged", "test_description",
        "threshold_value", "column_name",
    }
    saved.validate.side_effect = InvalidTestDefinitionFields(
        {"severity": "must be `Fail` or `Warning` (got `critical`)"}
    )
    mock_td.return_value = saved

    from testgen.mcp.tools.test_definitions import create_test

    with pytest.raises(MCPUserError) as exc_info:
        create_test(
            test_suite_id=str(uuid4()),
            test_type="Alpha Truncation",
            table_name="orders",
            fields={"column_name": "email", "threshold_value": "64", "severity": "critical"},
        )
    assert "severity" in str(exc_info.value)
    saved.save.assert_not_called()


# -- update_test --------------------------------------------------------------


def _make_td_orm(test_type="Alpha_Trunc", threshold_value="64", severity="Warning"):
    td = MagicMock()
    td.id = uuid4()
    td.test_type = test_type
    td.threshold_value = threshold_value
    td.severity = severity
    td.test_active = True
    td.lock_refresh = False
    td.flagged = False
    # Mirror TestDefinition.editable_fields(tt) for an Alpha_Trunc-shaped test type
    td.editable_fields.return_value = {
        "test_active", "severity", "lock_refresh", "flagged", "test_description",
        "threshold_value",
    }
    return td


@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_happy_path(mock_resolve_td, mock_tt_model, db_session_mock):
    td = _make_td_orm()
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    from testgen.mcp.tools.test_definitions import update_test

    result = update_test(str(td.id), fields={"threshold_value": "80"})

    assert "updated" in result.lower()
    assert "threshold_value" in result
    assert "80" in result
    assert td.threshold_value == "80"
    td.save.assert_called_once()


@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_empty_fields_rejected(mock_resolve_td, mock_tt_model, db_session_mock):
    td = _make_td_orm()
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    from testgen.mcp.tools.test_definitions import update_test

    with pytest.raises(MCPUserError):
        update_test(str(td.id), fields={})
    td.save.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_unknown_field_rejected_no_partial(mock_resolve_td, mock_tt_model, db_session_mock):
    td = _make_td_orm()
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    from testgen.mcp.tools.test_definitions import update_test

    with pytest.raises(MCPUserError) as exc_info:
        # threshold_value is valid, table_name is not — must reject ALL
        update_test(str(td.id), fields={"threshold_value": "80", "table_name": "new"})
    assert "table_name" in str(exc_info.value)
    # td.threshold_value should NOT have been mutated
    assert td.threshold_value == "64"
    td.save.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_multi_field(mock_resolve_td, mock_tt_model, db_session_mock):
    td = _make_td_orm()
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    from testgen.mcp.tools.test_definitions import update_test

    result = update_test(
        str(td.id),
        fields={"threshold_value": "80", "severity": "Fail", "test_active": False},
    )
    assert "3 field" in result
    td.save.assert_called_once()


# -- validate_custom_test -----------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.validate_custom_query")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.Connection")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_validate_custom_test_would_pass_when_no_rows(
    mock_resolve_suite, mock_conn, mock_tg, mock_validate, db_session_mock,
):

    mock_resolve_suite.return_value = _make_suite()
    conn = MagicMock()
    conn.connection_name = "warehouse"
    conn.sql_flavor_code = "snowflake"
    conn.sql_flavor = "snowflake"
    mock_conn.get_by_table_group.return_value = conn
    mock_tg.get.return_value = _make_table_group()
    mock_validate.return_value = CustomQueryResult(row_count=0, preview_rows=[])

    from testgen.mcp.tools.test_definitions import validate_custom_test

    result = validate_custom_test(str(uuid4()), "SELECT 1 WHERE 1=0")

    assert "ran successfully" in result.lower()
    assert "would pass" in result.lower()
    assert "0 rows matching the failure criteria" in result


@patch("testgen.mcp.permissions._compute_project_permissions")
@patch("testgen.mcp.tools.test_definitions.validate_custom_query")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.Connection")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_validate_custom_test_would_fail_shows_preview_with_view_pii(
    mock_resolve_suite, mock_conn, mock_tg, mock_validate, mock_compute, db_session_mock,
):
    from testgen.mcp.permissions import ProjectPermissions

    # Grant view_pii on "demo" so values are visible in the preview.
    perms = MagicMock(spec=ProjectPermissions)
    perms.allowed_codes = ["demo"]
    perms.codes_allowed_to.return_value = ["demo"]
    perms.has_access.side_effect = lambda code: code == "demo"
    mock_compute.return_value = perms

    mock_resolve_suite.return_value = _make_suite()
    conn = MagicMock()
    conn.connection_name = "warehouse"
    conn.sql_flavor_code = "snowflake"
    conn.sql_flavor = "snowflake"
    mock_conn.get_by_table_group.return_value = conn
    mock_tg.get.return_value = _make_table_group()

    row = MagicMock()
    row.keys.return_value = ["order_id", "amount"]
    row.__getitem__.side_effect = lambda k: {"order_id": "ORD-123", "amount": "-45.99"}[k]
    mock_validate.return_value = CustomQueryResult(row_count=3, preview_rows=[row])

    from testgen.mcp.tools.test_definitions import validate_custom_test

    result = validate_custom_test(str(uuid4()), "SELECT * FROM orders WHERE amount < 0")

    assert "would fail" in result.lower()
    assert "3 row(s) matching the failure criteria" in result
    assert "order_id" in result
    assert "ORD-123" in result
    assert "[redacted]" not in result


@patch("testgen.mcp.tools.test_definitions.validate_custom_query")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.Connection")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_validate_custom_test_redacts_when_no_view_pii(
    mock_resolve_suite, mock_conn, mock_tg, mock_validate, db_session_mock,
):

    # Default fixture user has role_a with edit but not view_pii.
    mock_resolve_suite.return_value = _make_suite()
    conn = MagicMock()
    conn.connection_name = "warehouse"
    conn.sql_flavor_code = "snowflake"
    conn.sql_flavor = "snowflake"
    mock_conn.get_by_table_group.return_value = conn
    mock_tg.get.return_value = _make_table_group()

    row = MagicMock()
    row.keys.return_value = ["order_id", "customer_email"]
    row.__getitem__.side_effect = lambda k: {"order_id": "ORD-123", "customer_email": "jane@example.com"}[k]
    mock_validate.return_value = CustomQueryResult(row_count=1, preview_rows=[row])

    from testgen.mcp.tools.test_definitions import validate_custom_test

    result = validate_custom_test(str(uuid4()), "SELECT * FROM orders")

    # Column names always visible
    assert "order_id" in result
    assert "customer_email" in result
    # Values redacted; PII footer mentions permissions (no `view_pii` jargon)
    assert "[redacted]" in result
    assert "jane@example.com" not in result
    assert "ORD-123" not in result
    assert "permissions to view PII" in result
    assert "view_pii" not in result


@patch("testgen.mcp.tools.test_definitions.validate_custom_query")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.Connection")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_validate_custom_test_sql_error_surfaced(
    mock_resolve_suite, mock_conn, mock_tg, mock_validate, db_session_mock,
):
    mock_resolve_suite.return_value = _make_suite()
    conn = MagicMock()
    conn.connection_name = "warehouse"
    conn.sql_flavor_code = "postgresql"
    conn.sql_flavor = "postgresql"
    mock_conn.get_by_table_group.return_value = conn
    mock_tg.get.return_value = _make_table_group()
    mock_validate.side_effect = Exception('syntax error at or near "FROMM"')

    from testgen.mcp.tools.test_definitions import validate_custom_test

    result = validate_custom_test(str(uuid4()), "SELECT * FROMM orders")

    assert "did not execute" in result.lower()
    assert "syntax error" in result


@patch("testgen.mcp.tools.test_definitions.Connection")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_validate_custom_test_missing_connection(mock_resolve_suite, mock_conn, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    mock_conn.get_by_table_group.return_value = None

    from testgen.mcp.tools.test_definitions import validate_custom_test

    with pytest.raises(MCPUserError, match="No connection"):
        validate_custom_test(str(uuid4()), "SELECT 1")


# -- bulk_update_tests --------------------------------------------------------


@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_disable_no_filter(mock_resolve_suite, mock_session, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    result_mock = MagicMock()
    result_mock.rowcount = 3
    mock_session.return_value.execute.return_value = result_mock

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(test_suite_id=str(uuid4()), action="disable")

    assert "Disabled" in result
    assert "3 test" in result
    assert "no filter" in result


@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_enable_with_table_filter(
    mock_resolve_suite, mock_resolve_tt, mock_session, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    mock_session.return_value.execute.return_value = result_mock

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(
        test_suite_id=str(uuid4()), action="enable", table_name="legacy_orders"
    )

    assert "Enabled" in result
    assert "legacy_orders" in result
    mock_resolve_tt.assert_not_called()  # not called when test_type filter absent


@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_invalid_action(mock_resolve_suite, mock_session, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    with pytest.raises(MCPUserError, match="`action`"):
        bulk_update_tests(test_suite_id=str(uuid4()), action="toggle")

    # Suite resolution happens before action validation in current code path?
    # Actually, action is validated first; resolve_test_suite shouldn't have been called.
    mock_resolve_suite.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_no_match(mock_resolve_suite, mock_session, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    result_mock = MagicMock()
    result_mock.rowcount = 0
    mock_session.return_value.execute.return_value = result_mock

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(test_suite_id=str(uuid4()), action="disable", table_name="nonexistent")

    assert "No tests matched" in result
    assert "nonexistent" in result
