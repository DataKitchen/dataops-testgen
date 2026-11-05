import asyncio
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from mcp.types import ElicitationCapability
from sqlalchemy.dialects import postgresql

from testgen.common.custom_test_validation import CustomQueryResult
from testgen.common.enums import SuiteType
from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY
from testgen.common.models.suite_version import (
    FrozenVersionError,
    RemovedInDraftError,
    SuiteVersion,
    UnmatchedInDraftError,
    VersionState,
)
from testgen.common.models.test_definition import ManagedTestDefinitionError, TestDefinition, TestDefinitionNote
from testgen.mcp import confirmation
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.tools.test_definitions import (
    _DELETED_LISTING_LIMIT,
    bulk_update_tests,
    create_test,
    delete_tests,
    export_tests,
    get_test,
    import_tests,
    list_tests,
    resolved_version,
    update_test,
)
from tests.unit.sql_assertions import conjuncts, emitted_statements, equality_conjunct, scopes_to_a_version

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
    assert "Last Generated" in result  # header
    assert "2026-04-01" in result
    mock_td.list_for_suite.assert_called_once()
    call_kwargs = mock_td.list_for_suite.call_args
    assert call_kwargs.kwargs["test_suite_id"] is not None
    assert call_kwargs.kwargs["page"] == 1
    assert call_kwargs.kwargs["limit"] == 50


@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.common.TestSuite")
def test_list_tests_suite_not_found_or_inaccessible(mock_suite_cls, mock_td, db_session_mock):
    """A suite that cannot be resolved is reported as not found, rather than read as a suite with no tests."""
    mock_suite_cls.get.return_value = None

    from testgen.mcp.tools.test_definitions import list_tests

    with pytest.raises(MCPResourceNotAccessible, match="Test suite .* not found or not accessible"):
        list_tests(str(uuid4()))
    mock_td.list_for_suite.assert_not_called()


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


@pytest.mark.parametrize(("test_severity", "suite_severity", "shown"), [
    ("Warning", "Log", "**Severity:** Warning"),
    (None, "Log", "**Severity:** Log (test suite default)"),
    (None, None, "**Severity:** Fail (test type default)"),
])
@patch("testgen.mcp.tools.test_definitions.TestSuite")
@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestResult")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_shows_the_severity_execution_applies(
    mock_td, mock_tr, mock_notes, mock_suite, test_severity, suite_severity, shown, db_session_mock,
):
    td = MagicMock(
        id=uuid4(), display_name="Row Count", column_name=None, table_name="orders", test_scope=None,
        impact_dimension=None, default_impact_dimension=None, dq_dimension=None, flagged=False,
        severity=test_severity, default_severity="Fail", export_to_observability=False, last_auto_gen_date=None,
        profiling_as_of_date=None, last_manual_update=None, external_url=None, custom_metadata=None,
        param_columns=set(), param_fields=[], test_description=None, default_test_description=None, usage_notes=None,
    )
    mock_td.get_for_project.return_value = td
    mock_notes.get_notes.return_value = []
    mock_tr.select_history.return_value = []
    mock_suite.get.return_value = MagicMock(suite_type=SuiteType.REGULAR, severity=suite_severity)

    from testgen.mcp.tools.test_definitions import get_test

    assert shown in get_test(str(td.id))


@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_list_tests_shows_the_suite_default_severity_for_a_test_without_one(
    mock_td, mock_notes, mock_resolve, db_session_mock,
):
    mock_resolve.return_value = MagicMock(id=uuid4(), suite_type=SuiteType.REGULAR, severity="Log")
    item = MagicMock(
        display_name="Row Count", table_name="orders", column_name=None, test_active=True, severity=None,
        default_severity="Fail", lock_refresh=False, flagged=False, last_auto_gen_date=None, last_manual_update=None,
    )
    mock_td.list_for_suite.return_value = ([item], 1)
    mock_notes.get_notes_count_by_ids.return_value = {}

    from testgen.mcp.tools.test_definitions import list_tests

    row = next(line for line in list_tests(str(uuid4())).splitlines() if "Row Count" in line)
    assert "| Log |" in row
    assert "Fail" not in row


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


@patch("testgen.mcp.tools.test_definitions.mcp_source_data_protected", return_value=True)
@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestResult")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_drops_calibration_params_when_source_data_protected(
    mock_td, mock_tr, mock_notes, _mock_flag, db_session_mock,
):
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
    td.default_parm_columns = "threshold_value,baseline_value,subset_condition"
    td.param_columns = {"threshold_value", "baseline_value", "subset_condition"}
    td.param_fields = [
        ("threshold_value", "Threshold", ""),
        ("baseline_value", "Baseline", ""),
        ("subset_condition", "Subset condition", ""),
    ]
    td.threshold_value = "5.0"
    td.baseline_value = "3.0"
    td.subset_condition = "status = 'active'"
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

    # Calibration-shaped columns filtered from Parameters; user-authored keep.
    assert "threshold_value" not in result
    assert "baseline_value" not in result
    assert "5.0" not in result
    assert "3.0" not in result
    assert "subset_condition" in result
    assert "status = 'active'" in result


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
    td.profiling_as_of_date = datetime(2026, 3, 14)
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
    assert "**Last Generated:** 2026-03-15" in result
    assert "**Based on Profiling:** 2026-03-14" in result
    assert "**Last Manual Update:** Never" in result


_RULES_MODULE = "testgen.common.database.table_group_service"


def _patch_table_group_flavor(sql_flavor_code):
    """Report the table group's connection as this database type to the flavor lookups.

    Both the family and the code are set: the family resolves the flavor service, and the code
    decides whether it qualifies table references.
    """
    connection = MagicMock()
    connection.sql_flavor = FLAVOR_CODE_TO_FAMILY[sql_flavor_code]
    connection.sql_flavor_code = sql_flavor_code
    return patch(f"{_RULES_MODULE}.Connection.get_by_table_group", return_value=connection)



def _minimal_test_definition() -> MagicMock:
    td = MagicMock()
    td.id = uuid4()
    td.table_groups_id = uuid4()
    td.test_type = "Alpha_Trunc"
    td.display_name = "Alpha Truncation"
    td.table_name = "orders"
    td.column_name = "customer_name"
    td.schema_name = "main"
    td.test_suite_id = uuid4()
    td.param_columns = {"match_schema_name", "match_table_name"}
    td.param_fields = []
    td.match_schema_name = "reference"
    td.match_table_name = "customers"
    td.custom_query = None
    td.last_manual_update = None
    td.last_auto_gen_date = None
    td.test_description = None
    td.default_test_description = None
    td.usage_notes = None
    return td


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestResult")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_reports_no_schema_on_a_files_connection(mock_td, mock_tr, mock_notes, db_session_mock):
    """The stored value is the engine's own default schema, not one the user chose."""
    td = _minimal_test_definition()
    mock_td.get_for_project.return_value = td
    mock_tr.select_history.return_value = []
    mock_notes.get_notes.return_value = []

    from testgen.mcp.tools.test_definitions import get_test

    with _patch_table_group_flavor("files"):
        result = get_test(str(td.id))

    assert "Schema" not in result
    assert "`main`" not in result
    assert "`orders`" in result


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestResult")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_names_the_data_space_on_a_data_360_connection(mock_td, mock_tr, mock_notes, db_session_mock):
    td = _minimal_test_definition()
    td.schema_name = "sales"
    td.test_scope = "referential"
    mock_td.get_for_project.return_value = td
    mock_tr.select_history.return_value = []
    mock_notes.get_notes.return_value = []

    from testgen.mcp.tools.test_definitions import get_test

    with _patch_table_group_flavor("salesforce_data360"):
        result = get_test(str(td.id))

    assert "**Data Space:** `sales`" in result
    assert "Schema" not in result
    # The reference table's schema is a SQL question, not a naming one: Data 360 reaches every
    # table through one data space, so the field is settled rather than offered.
    assert "Match Data Space" not in result
    assert "match_schema_name" not in result
    assert "**Match Table:** `customers`" in result


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestResult")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
def test_get_test_shows_no_reference_match_for_a_custom_test(mock_td, mock_tr, mock_notes, db_session_mock):
    td = _minimal_test_definition()
    td.test_type = "CUSTOM"
    td.test_scope = "custom"
    td.param_columns = {"custom_query", "match_column_names"}
    td.match_column_names = None
    mock_td.get_for_project.return_value = td
    mock_tr.select_history.return_value = []
    mock_notes.get_notes.return_value = []

    from testgen.mcp.tools.test_definitions import get_test

    with _patch_table_group_flavor("postgresql"):
        result = get_test(str(td.id))

    assert "Reference Match" not in result


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
    assert "Notes: 2." in result
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
        {"column_name": "required for test type `Alpha Truncation`"}
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
        {"severity": "must be one of `Fail`, `Warning`, `Log` (got `critical`)"}
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
def test_update_test_refuses_a_managed_test(mock_resolve_td, mock_tt_model, db_session_mock):
    td = _make_td_orm(test_type="Schema_Conformance")
    mock_resolve_td.return_value = td

    from testgen.mcp.tools.test_definitions import update_test

    with pytest.raises(MCPUserError, match=f"Test definition `{td.id}` is managed by TestGen"):
        update_test(str(td.id), fields={"severity": "Fail"})

    td.save.assert_not_called()
    mock_tt_model.get.assert_not_called()


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
    assert "Fields changed: 3." in result
    td.save.assert_called_once()


@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_reports_only_the_fields_that_change(mock_resolve_td, mock_tt_model, db_session_mock):
    td = _make_td_orm(threshold_value="64", severity="Warning")
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    from testgen.mcp.tools.test_definitions import update_test

    result = update_test(str(td.id), fields={"threshold_value": "64", "severity": "Fail"})

    assert "| `severity` | Warning | Fail |" in result
    assert "`threshold_value`" not in result
    assert "Fields changed: 1." in result
    td.save.assert_called_once()


@pytest.mark.parametrize(
    ("field", "stored", "sent"),
    [
        ("severity", "Warning", "Warning"),
        ("severity", None, ""),
        ("severity", "", None),
        ("severity", None, None),
        ("custom_metadata", {"task": "t1", "pipeline": "p1"}, {"pipeline": "p1", "task": "t1"}),
        ("test_active", True, "Y"),
        ("test_active", True, "yes"),
        ("lock_refresh", False, "N"),
        ("flagged", True, "yes"),
        ("skip_errors", 0, None),
        ("skip_errors", 0, ""),
        ("skip_errors", 3, "3"),
    ],
)
def test_update_test_that_changes_nothing_saves_nothing(db_session_mock, field, stored, sent):
    """A no-op edit saves nothing and rolls back the draft that routing a frozen row may have opened."""
    td = _orm_td(id=uuid4(), version_id=uuid4(), **{field: stored})
    td.editable_fields.return_value = td.editable_fields.return_value | {field}
    td.last_manual_update = "unchanged"
    with (
        _update_context(td, suite=_contract_suite(), old_version=3),
        patch.object(TestDefinition, "resolve_writable", return_value=(td.version_id, {td.id: td.id})),
        patch("testgen.mcp.tools.common.get_current_session") as session,
    ):
        result = update_test(str(td.id), fields={field: sent})

    assert "No fields changed — supplied values matched the current state." in result
    assert "Fields changed" not in result
    td.save.assert_not_called()
    session.return_value.rollback.assert_called_once()
    assert td.last_manual_update == "unchanged"


@pytest.mark.parametrize(("sent", "stored"), [("No", False), ("FALSE", False), (" n ", False), (False, False)])
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_reads_a_yes_no_string_as_a_boolean(mock_resolve_td, mock_tt_model, db_session_mock, sent, stored):
    td = _make_td_orm()
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    result = update_test(str(td.id), fields={"test_active": sent})

    assert td.test_active is stored
    assert "| `test_active` | Yes | No |" in result
    td.save.assert_called_once()


@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_reads_a_yes_no_string_as_a_boolean_flag(mock_resolve_td, mock_tt_model, db_session_mock):
    td = _make_td_orm()
    td.flagged = False
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    update_test(str(td.id), fields={"flagged": "yes"})

    assert td.flagged is True
    td.save.assert_called_once()


@pytest.mark.parametrize("sent", ["maybe", "", 1, None])
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_refuses_a_flag_that_is_not_yes_or_no(mock_resolve_td, mock_tt_model, db_session_mock, sent):
    td = _make_td_orm()
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    with pytest.raises(MCPUserError, match="`lock_refresh` must be true or false."):
        update_test(str(td.id), fields={"lock_refresh": sent})
    td.save.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.mcp_source_data_protected", return_value=True)
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_under_protection_never_says_a_hidden_value_matched(
    mock_resolve_td, mock_tt_model, _protected, db_session_mock
):
    """A "no change" answer would confirm a guess at a value reads hide, so a hidden field always counts as written."""
    td = _make_td_orm(threshold_value="64")
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    from testgen.mcp.tools.test_definitions import update_test

    result = update_test(str(td.id), fields={"threshold_value": "64"})

    assert "No fields changed" not in result
    assert "| `threshold_value` | — | 64 |" in result
    assert "Fields changed: 1." in result
    td.save.assert_called_once()


def test_update_by_an_active_id_compares_against_the_drafts_copy(db_session_mock):
    """The active row already holds the value, but the draft's copy does not, so the edit is real."""
    active_version, draft = uuid4(), SuiteVersion(id=uuid4(), version=4)
    active = _orm_td(id=uuid4(), version_id=active_version, severity="Warning")
    copy = _orm_td(id=uuid4(), version_id=draft.id, severity="Fail")
    rows = {active.id: active, copy.id: copy}
    with (
        _update_context(active, suite=_contract_suite(), versions={draft.id: draft}, old_version=3),
        patch(
            "testgen.mcp.tools.test_definitions.resolve_test_definition",
            side_effect=lambda row_id: rows[UUID(row_id)],
        ),
        patch.object(TestDefinition, "resolve_writable", return_value=(draft.id, {active.id: copy.id})),
    ):
        out = update_test(str(active.id), fields={"severity": "Warning"})

    assert "| `severity` | Fail | Warning |" in out
    copy.save.assert_called_once()


@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_custom_metadata_json_string_coerced(mock_resolve_td, mock_tt_model, db_session_mock):
    td = _make_td_orm()
    td.editable_fields.return_value = td.editable_fields.return_value | {"custom_metadata"}
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    from testgen.mcp.tools.test_definitions import update_test

    update_test(str(td.id), fields={"custom_metadata": '{"pipeline": "p1", "task": "t1"}'})
    assert td.custom_metadata == {"pipeline": "p1", "task": "t1"}
    td.save.assert_called_once()


@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_custom_metadata_invalid_json_rejected(mock_resolve_td, mock_tt_model, db_session_mock):
    td = _make_td_orm()
    td.editable_fields.return_value = td.editable_fields.return_value | {"custom_metadata"}
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    from testgen.mcp.tools.test_definitions import update_test

    with pytest.raises(MCPUserError, match="custom_metadata"):
        update_test(str(td.id), fields={"custom_metadata": "{not valid json"})
    td.save.assert_not_called()


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
    assert "3 rows matching the failure criteria" in result
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


@pytest.fixture
def routes_in_place():
    """Route every named row to itself, as for a regular suite, and read its suite as one."""
    with (
        patch.object(
            TestDefinition,
            "resolve_writable",
            side_effect=lambda _suite_id, row_ids=(): (uuid4(), {row_id: row_id for row_id in row_ids}),
        ),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=_make_suite()),
    ):
        yield


def _matched_row(row_id=None, test_type="Alpha_Trunc"):
    """A row of the ``(id, test_type)`` select ``bulk_update_tests`` runs on a suite filter."""
    return MagicMock(id=row_id or uuid4(), test_type=test_type)


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_disable_no_filter(mock_resolve_suite, mock_session, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    mock_session.return_value.execute.return_value.all.return_value = [_matched_row(), _matched_row(), _matched_row()]

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(test_suite_id=str(uuid4()), action="disable")

    assert "Disabled 3 tests in suite `demo_suite`" in result
    assert "no filter" in result
    assert "Version" not in result


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_enable_with_table_filter(
    mock_resolve_suite, mock_resolve_tt, mock_session, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    mock_session.return_value.execute.return_value.all.return_value = [_matched_row()]

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

    with pytest.raises(MCPUserError, match="Invalid action `toggle`"):
        bulk_update_tests(test_suite_id=str(uuid4()), action="toggle")

    # Suite resolution happens before action validation in current code path?
    # Actually, action is validated first; resolve_test_suite shouldn't have been called.
    mock_resolve_suite.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_no_match(mock_resolve_suite, mock_session, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    mock_session.return_value.execute.return_value.all.return_value = []

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(test_suite_id=str(uuid4()), action="disable", table_name="nonexistent")

    assert "No tests matched" in result
    assert "nonexistent" in result


# -- export_tests / import_tests ----------------------------------------------


def _make_export_document(definitions=None):
    from datetime import UTC, datetime

    from testgen.common.test_definition_export_import_service import (
        ExportDocument,
        ExportSource,
        TestDefinitionExport,
    )

    return ExportDocument(
        version=1,
        source=ExportSource(
            project_code="demo",
            test_suite="demo_suite",
            table_group="tg",
            table_group_schema="public",
            exported_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        definitions=definitions
        if definitions is not None
        else [TestDefinitionExport(test_type="Row_Ct", table_name="orders")],
    )


def _make_import_response(*, created=0, updated=0, skipped=0, deleted=0, items=None, version=None):
    from testgen.common.test_definition_export_import_service import ImportResponse, ImportSummary

    return ImportResponse(
        summary=ImportSummary(created=created, updated=updated, skipped=skipped, deleted=deleted),
        items=items or [],
        version=version,
    )


@patch("testgen.mcp.tools.test_definitions.export_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_export_tests_basic(mock_resolve_suite, mock_export, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    mock_export.return_value = _make_export_document()

    from testgen.mcp.tools.test_definitions import export_tests

    result = export_tests(test_suite_id=str(uuid4()))

    assert "Test Definition Export from suite `demo_suite`" in result
    assert "Tests Exported" in result
    assert "```json" in result  # payload rendered as a fenced JSON block
    assert "Row_Ct" in result
    # default origin=both → no Filters line
    assert "Filters" not in result


@patch("testgen.mcp.tools.test_definitions.export_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_export_tests_with_filters(mock_resolve_suite, mock_resolve_tt, mock_export, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    mock_resolve_tt.return_value = "Row_Ct"
    mock_export.return_value = _make_export_document()

    from testgen.mcp.tools.test_definitions import export_tests

    result = export_tests(test_suite_id=str(uuid4()), origin="manual", table_name="orders", test_type="Row Count")

    assert "Filters" in result
    assert "manual tests only" in result
    assert "table `orders`" in result
    mock_resolve_tt.assert_called_once_with("Row Count")
    # origin code, not label, is forwarded to the service
    assert mock_export.call_args.args[1].value == "manual"


@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_export_tests_invalid_origin(mock_resolve_suite, db_session_mock):
    from testgen.mcp.tools.test_definitions import export_tests

    with pytest.raises(MCPUserError, match="Invalid origin `sideways`"):
        export_tests(test_suite_id=str(uuid4()), origin="sideways")


@patch("testgen.mcp.tools.test_definitions.import_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_import_tests_preview(mock_resolve_suite, mock_import, db_session_mock):
    from testgen.common.test_definition_export_import_service import (
        ImportAction,
        ImportItem,
        ImportItemTD,
        ImportReason,
    )

    mock_resolve_suite.return_value = _make_suite()
    mock_import.return_value = _make_import_response(
        created=1,
        updated=1,
        items=[
            ImportItem(action=ImportAction.create, reason=ImportReason.no_match, tds=[ImportItemTD(idx=0, target_id=uuid4())]),
            ImportItem(action=ImportAction.update, reason=ImportReason.matched, tds=[ImportItemTD(idx=1, target_id=uuid4())]),
        ],
    )

    from testgen.mcp.tools.test_definitions import import_tests

    result = import_tests(test_suite_id=str(uuid4()), payload='{"definitions": []}')

    assert "Import Preview" in result
    assert "no changes were persisted" in result
    assert "Created (projected)" in result
    assert "Create (1)" in result
    assert "Update (1)" in result


_NOT_IN_CATALOG_HINT = (
    "The data catalog lists the tables and columns TestGen found in the table group's schema. Check the table "
    "and column names in the import file, or profile the table group to refresh the catalog."
)


@patch("testgen.mcp.tools.test_definitions.import_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_import_tests_names_reasons_and_explains_names_missing_from_the_catalog(
    mock_resolve_suite, mock_import, db_session_mock,
):
    from testgen.common.test_definition_export_import_service import (
        ImportAction,
        ImportItem,
        ImportItemTD,
        ImportReason,
    )

    mock_resolve_suite.return_value = _make_suite()
    mock_import.return_value = _make_import_response(
        created=1,
        skipped=3,
        items=[
            ImportItem(action=ImportAction.create, reason=ImportReason.no_match, tds=[ImportItemTD(idx=0)]),
            ImportItem(
                action=ImportAction.skip,
                reason=ImportReason.invalid_table,
                tds=[ImportItemTD(idx=1), ImportItemTD(idx=2)],
            ),
            ImportItem(action=ImportAction.skip, reason=ImportReason.invalid_column, tds=[ImportItemTD(idx=3)]),
        ],
    )

    from testgen.mcp.tools.test_definitions import import_tests

    result = import_tests(test_suite_id=str(uuid4()), payload='{"definitions": []}')

    assert "| No matching test | 0 |" in result
    assert "| Table not in the data catalog | 1 |" in result
    assert "| Column not in the data catalog | 3 |" in result
    assert "invalid_table" not in result
    assert "invalid_column" not in result
    assert result.count(_NOT_IN_CATALOG_HINT) == 1


@patch("testgen.mcp.tools.test_definitions.import_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_import_tests_explains_a_column_missing_from_the_catalog(mock_resolve_suite, mock_import, db_session_mock):
    from testgen.common.test_definition_export_import_service import (
        ImportAction,
        ImportItem,
        ImportItemTD,
        ImportReason,
    )

    mock_resolve_suite.return_value = _make_suite()
    mock_import.return_value = _make_import_response(
        skipped=1,
        items=[ImportItem(action=ImportAction.skip, reason=ImportReason.invalid_column, tds=[ImportItemTD(idx=0)])],
    )

    from testgen.mcp.tools.test_definitions import import_tests

    result = import_tests(test_suite_id=str(uuid4()), payload='{"definitions": []}')

    assert _NOT_IN_CATALOG_HINT in result


@patch("testgen.mcp.tools.test_definitions.import_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_import_tests_without_missing_tables_has_no_catalog_hint(mock_resolve_suite, mock_import, db_session_mock):
    from testgen.common.test_definition_export_import_service import (
        ImportAction,
        ImportItem,
        ImportItemTD,
        ImportReason,
    )

    mock_resolve_suite.return_value = _make_suite()
    mock_import.return_value = _make_import_response(
        skipped=1,
        items=[ImportItem(action=ImportAction.skip, reason=ImportReason.locked, tds=[ImportItemTD(idx=0)])],
    )

    from testgen.mcp.tools.test_definitions import import_tests

    result = import_tests(test_suite_id=str(uuid4()), payload='{"definitions": []}')

    assert "Existing test is locked" in result
    assert "data catalog" not in result


@patch("testgen.mcp.tools.test_definitions.import_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_import_tests_apply(mock_resolve_suite, mock_import, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    mock_import.return_value = _make_import_response(created=2)

    from testgen.mcp.tools.test_definitions import import_tests

    result = import_tests(test_suite_id=str(uuid4()), payload='{"definitions": []}', mode="apply")

    assert "Import into suite `demo_suite`" in result
    assert "no changes were persisted" not in result
    assert "Created" in result
    # applied mode → no "(projected)" suffix
    assert "(projected)" not in result


@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_import_tests_invalid_mode(mock_resolve_suite, db_session_mock):
    from testgen.mcp.tools.test_definitions import import_tests

    with pytest.raises(MCPUserError, match="Invalid mode `yolo`"):
        import_tests(test_suite_id=str(uuid4()), payload='{"definitions": []}', mode="yolo")


@patch("testgen.mcp.tools.test_definitions.import_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_import_tests_malformed_payload(mock_resolve_suite, mock_import, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()

    from testgen.mcp.tools.test_definitions import import_tests

    with pytest.raises(MCPUserError, match="not a valid export document"):
        import_tests(test_suite_id=str(uuid4()), payload="{not json")
    mock_import.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.import_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_import_tests_domain_error_surfaced(mock_resolve_suite, mock_import, db_session_mock):
    from testgen.common.test_definition_export_import_service import ImportErrorCode, InvalidImportPayload

    mock_resolve_suite.return_value = _make_suite()
    mock_import.side_effect = InvalidImportPayload(
        ImportErrorCode.duplicate_natural_key, "Duplicate auto-gen key at index 1"
    )

    from testgen.mcp.tools.test_definitions import import_tests

    with pytest.raises(MCPUserError, match="Duplicate auto-gen key at index 1"):
        import_tests(test_suite_id=str(uuid4()), payload='{"definitions": []}', mode="apply")


@patch("testgen.mcp.tools.test_definitions.import_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_import_tests_strict_violation_embeds_breakdown(mock_resolve_suite, mock_import, db_session_mock):
    from testgen.common.test_definition_export_import_service import (
        ImportAction,
        ImportItem,
        ImportItemTD,
        ImportReason,
        ImportStrictViolation,
    )

    mock_resolve_suite.return_value = _make_suite()
    result = _make_import_response(
        created=1,
        skipped=1,
        items=[
            ImportItem(action=ImportAction.create, reason=ImportReason.no_match, tds=[ImportItemTD(idx=0)]),
            ImportItem(action=ImportAction.skip, reason=ImportReason.invalid_test_type, tds=[ImportItemTD(idx=1)]),
        ],
    )
    mock_import.side_effect = ImportStrictViolation(result)

    from testgen.mcp.tools.test_definitions import import_tests

    with pytest.raises(MCPUserError) as exc_info:
        import_tests(test_suite_id=str(uuid4()), payload='{"definitions": []}', mode="apply_strict")

    msg = str(exc_info.value)
    assert "Strict import failed" in msg
    assert "1 tests would be skipped" in msg
    assert "Nothing was applied" in msg
    # the projected breakdown is embedded
    assert "Skip (1)" in msg
    assert "Unknown test type" in msg
    assert "invalid_test_type" not in msg


# --- Schema exclusion from the regular-test surfaces ---


@patch("testgen.mcp.tools.test_definitions.TestType")
def test_list_test_types_applies_public_filter(mock_tt, db_session_mock):
    """The catalog a caller picks a test type from excludes the non-public types."""
    mock_tt.select_where.return_value = []

    from testgen.mcp.tools.test_definitions import list_test_types

    list_test_types()

    mock_tt.is_public.assert_called_once()
    assert mock_tt.is_public.return_value in mock_tt.select_where.call_args.args


@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_create_test_rejects_non_public_test_type(
    mock_resolve_suite, mock_resolve_tt, mock_tt_model, mock_tg, db_session_mock,
):
    from testgen.common.enums import MonitorType

    mock_resolve_suite.return_value = _make_suite()
    mock_resolve_tt.return_value = MonitorType.SCHEMA.value
    schema_type = MagicMock()
    schema_type.test_type = MonitorType.SCHEMA.value
    schema_type.test_name_short = "Schema"
    mock_tt_model.get.return_value = schema_type

    from testgen.mcp.tools.test_definitions import create_test

    with pytest.raises(MCPUserError, match="Schema is not an available test type") as exc_info:
        create_test(test_suite_id=str(uuid4()), test_type="Schema", table_name="orders")

    assert MonitorType.SCHEMA.value not in str(exc_info.value)
    mock_tg.get.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_create_test_rejects_volume_trend(
    mock_resolve_suite, mock_resolve_tt, mock_tt_model, mock_tg, db_session_mock,
):
    from testgen.common.enums import MonitorType

    mock_resolve_suite.return_value = _make_suite()
    mock_resolve_tt.return_value = MonitorType.VOLUME.value
    volume_type = _make_test_type(code=MonitorType.VOLUME.value, short_name="Volume Trend")
    mock_tt_model.get.return_value = volume_type

    from testgen.mcp.tools.test_definitions import create_test

    with pytest.raises(MCPUserError, match="Volume Trend is not an available test type"):
        create_test(test_suite_id=str(uuid4()), test_type="Volume Trend", table_name="orders")

    mock_tg.get.assert_not_called()


@patch("testgen.common.contract_rules.SuiteVersion")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_create_test_refuses_a_table_the_contract_does_not_declare(
    mock_resolve_suite, mock_resolve_tt, mock_tt_model, mock_tg, mock_td, mock_version, db_session_mock,
):
    from testgen.common.enums import SuiteType

    suite = _make_suite()
    suite.suite_type = SuiteType.CONTRACT
    mock_resolve_suite.return_value = suite
    mock_resolve_tt.return_value = "Row_Ct"
    mock_tt_model.get.return_value = _make_test_type(code="Row_Ct", short_name="Row Count", scope="table")
    mock_tg.get.return_value = _make_table_group()
    mock_version.draft_for.return_value = MagicMock(
        metadata_document={"schema": [{"name": "orders"}, {"name": "payments"}]}
    )

    from testgen.mcp.tools.test_definitions import create_test

    with pytest.raises(MCPUserError) as exc_info:
        create_test(test_suite_id=str(uuid4()), test_type="Row Count", table_name="customers")

    assert str(exc_info.value) == (
        "Test definition creation rejected. No changes saved.\n\nContract `demo_suite` does not declare table "
        "`customers`. A test on a contract can only target a table the contract declares. "
        "Declared tables: `orders`, `payments`."
    )
    mock_td.assert_not_called()


@patch("testgen.common.contract_rules.SuiteVersion")
@patch("testgen.mcp.tools.test_definitions.TestDefinition")
@patch("testgen.mcp.tools.test_definitions.TableGroup")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_create_test_on_a_contract_that_declares_no_tables_says_so(
    mock_resolve_suite, mock_resolve_tt, mock_tt_model, mock_tg, mock_td, mock_version, db_session_mock,
):
    from testgen.common.enums import SuiteType

    suite = _make_suite()
    suite.suite_type = SuiteType.CONTRACT
    mock_resolve_suite.return_value = suite
    mock_resolve_tt.return_value = "Row_Ct"
    mock_tt_model.get.return_value = _make_test_type(code="Row_Ct", short_name="Row Count", scope="table")
    mock_tg.get.return_value = _make_table_group()
    mock_version.draft_for.return_value = MagicMock(metadata_document={})

    from testgen.mcp.tools.test_definitions import create_test

    with pytest.raises(MCPUserError, match="The contract declares no tables.$"):
        create_test(test_suite_id=str(uuid4()), test_type="Row Count", table_name="customers")
    mock_td.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_allows_existing_non_public_test_type(mock_resolve_td, mock_tt_model, db_session_mock):
    """A Volume Trend test already in a regular suite stays editable, though new ones cannot be created."""
    from testgen.common.enums import MonitorType
    from testgen.common.models.test_definition import NON_PUBLIC_TEST_TYPES

    assert MonitorType.VOLUME.value in NON_PUBLIC_TEST_TYPES
    td = _make_td_orm(test_type=MonitorType.VOLUME.value)
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type(
        code=MonitorType.VOLUME.value, short_name="Volume Trend",
    )

    from testgen.mcp.tools.test_definitions import update_test

    result = update_test(str(td.id), fields={"test_active": False})

    assert "updated" in result.lower()
    assert td.test_active is False
    td.save.assert_called_once()


# -- version scoping ----------------------------------------------------------


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_scopes_to_a_version(mock_resolve_suite, mock_session, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    session = MagicMock()
    session.execute.return_value.all.return_value = [_matched_row()]
    mock_session.return_value = session

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    bulk_update_tests(test_suite_id=str(uuid4()), action="disable")

    statements = emitted_statements(session)
    assert len(statements) == 2, "one select of the matches, one update of their writable rows"
    assert all(scopes_to_a_version(statement) for statement in statements), (
        "the bulk update reads or writes every version of the suite, not the one it resolves to"
    )


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions._set_test_values")
@patch.object(TestDefinition, "list_for_ids")
def test_bulk_update_tests_by_ids_changes_only_the_named_tests(mock_list, mock_set, db_session_mock):
    suite_id = uuid4()
    named = [_make_td_minimal(test_id=uuid4()), _make_td_minimal(test_id=uuid4())]
    for td in named:
        td.test_suite_id = suite_id
    mock_list.return_value = named

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(action="disable", test_definition_ids=[str(td.id) for td in named])

    assert "Disabled 2 tests" in result
    assert "named in the request" in result
    assert "- **Test suite:** demo_suite" in result
    ids, values = mock_set.call_args.args
    assert sorted(ids, key=str) == sorted([td.id for td in named], key=str)
    assert values == {"test_active": False}


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions._set_test_values")
@patch.object(TestDefinition, "list_for_ids")
def test_bulk_update_tests_by_ids_across_suites_names_no_single_suite(mock_list, mock_set, db_session_mock):
    named = [_make_td_minimal(test_id=uuid4()), _make_td_minimal(test_id=uuid4())]
    for td in named:
        td.test_suite_id = uuid4()
    mock_list.return_value = named

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(action="enable", test_definition_ids=[str(td.id) for td in named])

    assert "Enabled 2 tests" in result
    assert "Test suite" not in result
    assert mock_set.call_args.args[1] == {"test_active": True, "test_definition_status": None}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"test_definition_ids": [str(uuid4())], "test_suite_id": str(uuid4())}, "not both"),
        ({}, "Supply either `test_definition_ids`"),
        ({"test_definition_ids": [str(uuid4())], "table_name": "orders"}, "cannot be combined"),
    ],
)
@patch("testgen.mcp.tools.test_definitions._set_test_values")
def test_bulk_update_tests_rejects_an_ambiguous_selection(mock_set, kwargs, message, db_session_mock):
    from testgen.mcp.tools.test_definitions import bulk_update_tests

    with pytest.raises(MCPUserError, match=message):
        bulk_update_tests(action="disable", **kwargs)
    mock_set.assert_not_called()


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions._set_test_values")
@patch.object(TestDefinition, "list_for_ids")
def test_bulk_update_tests_by_ids_keeps_the_tests_testgen_manages(mock_list, mock_set, db_session_mock):
    changed = _make_td_minimal(test_id=uuid4())
    managed = _make_td_minimal(test_id=uuid4(), test_type="Schema_Conformance")
    mock_list.return_value = [changed, managed]

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(action="disable", test_definition_ids=[str(changed.id), str(managed.id)])

    assert mock_set.call_args.args[0] == [changed.id]
    assert "Disabled 1 tests" in result
    assert "**Kept, managed by TestGen:** 1" in result


@patch("testgen.mcp.tools.test_definitions._set_test_values")
@patch.object(TestDefinition, "list_for_ids")
def test_bulk_update_tests_by_ids_naming_only_managed_tests_changes_nothing(mock_list, mock_set, db_session_mock):
    managed = _make_td_minimal(test_id=uuid4(), test_type="Schema_Conformance")
    mock_list.return_value = [managed]

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    with pytest.raises(MCPUserError, match="Nothing was changed. TestGen manages these tests, so they cannot be enabled") as error:
        bulk_update_tests(action="enable", test_definition_ids=[str(managed.id)])
    assert str(managed.id) in str(error.value)
    mock_set.assert_not_called()


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions._set_test_values")
@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_by_filter_keeps_the_tests_testgen_manages(
    mock_resolve_suite, mock_session, mock_set, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    changed = _matched_row()
    mock_session.return_value.execute.return_value.all.return_value = [changed, _matched_row(test_type="Schema_Conformance")]

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(test_suite_id=str(uuid4()), action="disable")

    assert mock_set.call_args.args[0] == [changed.id]
    assert "Disabled 1 tests in suite `demo_suite`" in result
    assert "**Kept, managed by TestGen:** 1" in result


@patch("testgen.mcp.tools.test_definitions._set_test_values")
@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_bulk_update_tests_by_filter_matching_only_managed_tests_changes_nothing(
    mock_resolve_suite, mock_session, mock_set, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    mock_session.return_value.execute.return_value.all.return_value = [_matched_row(test_type="Schema_Conformance")]

    from testgen.mcp.tools.test_definitions import bulk_update_tests

    result = bulk_update_tests(test_suite_id=str(uuid4()), action="disable")

    assert "# No tests to disable" in result
    assert "TestGen manages the 1 tests that matched the filter (no filter), so they cannot be disabled." in result
    mock_set.assert_not_called()


@patch("testgen.mcp.tools.test_definitions._set_test_values")
@patch.object(TestDefinition, "list_for_ids", return_value=[])
def test_bulk_update_tests_by_ids_changes_nothing_when_one_is_unusable(_mock_list, mock_set, db_session_mock):
    from testgen.mcp.tools.test_definitions import bulk_update_tests

    with pytest.raises(MCPUserError, match="Nothing was changed. Test definitions not found or not accessible"):
        bulk_update_tests(action="disable", test_definition_ids=[str(uuid4())])
    mock_set.assert_not_called()


# -- delete_tests -------------------------------------------------------------


def _confirming_ctx() -> MagicMock:
    """An MCP context whose client supports elicitation and whose user confirms."""
    ctx = MagicMock()
    ctx.session.client_params.capabilities.elicitation = ElicitationCapability()
    ctx.elicit = AsyncMock(return_value=MagicMock(action="accept", data=MagicMock(confirm=True)))
    return ctx


def _delete(**kwargs) -> str:
    """Call ``delete_tests`` as a user who confirms the delete."""
    return asyncio.run(delete_tests(_confirming_ctx(), **kwargs))


_DELETE_SUITE_ID = uuid4()


def _make_td_minimal(
    table_name="orders", column_name="email", test_id=None, test_type="Alpha_Trunc", test_suite_id=_DELETE_SUITE_ID
):
    """Mock TestDefinitionMinimal as returned by TestDefinition.list_for_ids / select_minimal_where."""
    td = MagicMock()
    td.id = test_id or uuid4()
    td.test_suite_id = test_suite_id
    td.test_type = test_type
    td.test_name_short = "Alpha Truncation"
    td.table_name = table_name
    td.column_name = column_name
    return td


def _deleted_ids(delete_where_mock) -> list:
    """The IDs the tool passed to ``delete_where`` as an ``id IN (...)`` clause."""
    id_clause = delete_where_mock.call_args.args[0]
    return list(id_clause.right.value)


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_by_ids_reports_what_went(mock_list, _mock_notes, mock_delete, db_session_mock):
    first, second = uuid4(), uuid4()
    mock_list.return_value = [
        _make_td_minimal(table_name="orders", test_id=first),
        _make_td_minimal(table_name="customers", column_name=None, test_id=second),
    ]

    result = _delete(test_definition_ids=[str(first), str(second)])

    assert "Deleted 2 tests" in result
    assert "the named tests in suite `demo_suite`" in result
    assert "orders" in result and "customers" in result
    assert str(first) in result and str(second) in result
    assert sorted(_deleted_ids(mock_delete), key=str) == sorted([first, second], key=str)


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where", side_effect=ManagedTestDefinitionError())
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_refuses_a_managed_test_as_a_user_error(
    mock_list, _mock_notes, _mock_delete, db_session_mock
):
    test_id = uuid4()
    mock_list.return_value = [_make_td_minimal(table_name="orders", column_name=None, test_id=test_id)]

    with pytest.raises(MCPUserError, match="TestGen manages this test"):
        _delete(test_definition_ids=[str(test_id)])


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_by_ids_resolves_in_one_query(mock_list, _mock_notes, _mock_delete, db_session_mock):
    """A named set of any size costs one statement per pass, not one per ID: one to plan the delete, one to make it."""
    ids = [uuid4() for _ in range(25)]
    mock_list.return_value = [_make_td_minimal(test_id=td_id) for td_id in ids]

    _delete(test_definition_ids=[str(td_id) for td_id in ids])

    assert mock_list.call_count == 2
    for lookup in mock_list.call_args_list:
        assert sorted(lookup.args[0], key=str) == sorted(ids, key=str)


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on")
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_reports_the_notes_that_went_with_them(
    mock_list, mock_notes, _mock_delete, db_session_mock
):
    """Notes are the one thing that cascades, so the count saves a follow-up read."""
    td_id = uuid4()
    mock_list.return_value = [_make_td_minimal(test_id=td_id)]
    mock_notes.return_value = 3

    result = _delete(test_definition_ids=[str(td_id)])

    assert "Notes deleted:** 3" in result


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_omits_the_note_count_when_there_were_none(
    mock_list, _mock_notes, _mock_delete, db_session_mock
):
    td_id = uuid4()
    mock_list.return_value = [_make_td_minimal(test_id=td_id)]

    assert "Notes deleted" not in _delete(test_definition_ids=[str(td_id)])


@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_by_ids_reports_every_unusable_entry_at_once(
    mock_list, mock_delete, db_session_mock
):
    """One round-trip fixes the whole list, and nothing is deleted meanwhile."""
    present, missing = uuid4(), uuid4()
    mock_list.return_value = [_make_td_minimal(test_id=present)]

    with pytest.raises(MCPUserError) as err:
        _delete(test_definition_ids=[str(present), "garbage", str(missing)])

    message = str(err.value)
    assert "Nothing was deleted" in message
    assert "not valid UUIDs: `garbage`" in message
    assert f"not found or not accessible: `{missing}`" in message
    assert str(present) not in message
    mock_delete.assert_not_called()


@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinition, "list_for_ids", return_value=[])
def test_delete_tests_by_ids_hides_whether_an_inaccessible_test_exists(
    _mock_list, mock_delete, db_session_mock
):
    td_id = uuid4()

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        _delete(test_definition_ids=[str(td_id)])

    mock_delete.assert_not_called()


@patch.object(TestDefinition, "list_for_ids", return_value=[])
def test_delete_tests_by_ids_scopes_the_lookup_to_allowed_projects(mock_list, db_session_mock):

    with pytest.raises(MCPUserError):
        _delete(test_definition_ids=[str(uuid4())])

    assert mock_list.call_args.args[1] == ["demo"]


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_by_ids_counts_a_repeated_id_once(
    mock_list, _mock_notes, mock_delete, db_session_mock
):
    td_id = uuid4()
    mock_list.return_value = [_make_td_minimal(test_id=td_id)]

    result = _delete(test_definition_ids=[str(td_id), str(td_id)])

    assert "Deleted 1 tests" in result
    assert _deleted_ids(mock_delete) == [td_id]
    assert mock_list.call_args.args[0] == [td_id]


def test_delete_tests_by_ids_rejects_an_empty_list(db_session_mock):

    with pytest.raises(MCPUserError, match="must name at least one test definition"):
        _delete(test_definition_ids=[])


def test_delete_tests_rejects_filters_alongside_named_ids(db_session_mock):
    """Silently ignoring them would delete a wider set than the caller described."""

    with pytest.raises(MCPUserError, match="cannot be combined with `test_definition_ids`"):
        _delete(test_definition_ids=[str(uuid4())], table_name="orders")


def test_delete_tests_requires_a_selection(db_session_mock):

    with pytest.raises(MCPUserError, match="Supply either"):
        _delete()


def test_delete_tests_rejects_both_selections(db_session_mock):
    """The two shapes select the same thing, so honouring both would be a guess."""

    with pytest.raises(MCPUserError, match="not both"):
        _delete(test_definition_ids=[str(uuid4())], test_suite_id=str(uuid4()))


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "select_minimal_where")
def test_delete_tests_by_suite_names_the_whole_suite_as_its_scope(
    mock_select, _mock_notes, mock_delete, mock_resolve_suite, db_session_mock
):
    """An unnarrowed filter is the one call whose blast radius the request does not show."""
    mock_resolve_suite.return_value = _make_suite()
    selected = [_make_td_minimal(table_name="orders"), _make_td_minimal(table_name="customers")]
    mock_select.return_value = selected

    result = _delete(test_suite_id=str(uuid4()))

    assert "Deleted 2 tests" in result
    assert "every test in suite `demo_suite`" in result
    assert _deleted_ids(mock_delete) == [td.id for td in selected]


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions.resolve_test_type", return_value="Alpha_Trunc")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "select_minimal_where")
def test_delete_tests_by_suite_names_the_filters_it_applied(
    mock_select, _mock_notes, _mock_delete, mock_resolve_suite, _mock_resolve_tt, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    mock_select.return_value = [_make_td_minimal()]

    result = _delete(
        test_suite_id=str(uuid4()), table_name="orders", test_type="Alpha Truncation"
    )

    assert "table_name=`orders`" in result
    assert "test_type=`Alpha Truncation`" in result
    assert "every test in suite" not in result


@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinition, "select_minimal_where", return_value=[])
def test_delete_tests_by_suite_deletes_nothing_when_nothing_matched(
    _mock_select, mock_delete, mock_resolve_suite, db_session_mock
):
    """The empty-result wording reads as a sentence, unlike the scope phrase."""
    mock_resolve_suite.return_value = _make_suite()

    result = _delete(test_suite_id=str(uuid4()), table_name="absent")

    assert "No tests in suite `demo_suite` matched the filter (table_name=`absent`)" in result
    mock_delete.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinition, "select_minimal_where", return_value=[])
def test_delete_tests_by_suite_names_an_unfiltered_empty_result_as_no_filter(
    _mock_select, _mock_delete, mock_resolve_suite, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()

    result = _delete(test_suite_id=str(uuid4()))

    assert "matched the filter (no filter)" in result


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "select_minimal_where")
def test_delete_tests_by_suite_accounts_for_a_listing_it_truncates(
    mock_select, _mock_notes, _mock_delete, mock_resolve_suite, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    mock_select.return_value = [_make_td_minimal() for _ in range(_DELETED_LISTING_LIMIT + 5)]

    result = _delete(test_suite_id=str(uuid4()))

    assert f"Deleted {_DELETED_LISTING_LIMIT + 5} tests" in result
    assert f"Listing {_DELETED_LISTING_LIMIT} of the {_DELETED_LISTING_LIMIT + 5} tests deleted" in result


# -- delete_tests: confirmation -----------------------------------------------


@pytest.fixture
def no_pending_tokens():
    confirmation._pending.clear()
    yield
    confirmation._pending.clear()


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "get_notes_count_by_ids", return_value={})
@patch.object(TestDefinitionNote, "count_stored_on", return_value=2)
@patch.object(TestDefinition, "select_minimal_where")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_delete_tests_asks_with_the_scope_and_counts_it_deletes(
    mock_resolve_suite, mock_select, _mock_stored_notes, mock_all_version_notes, _mock_delete, db_session_mock
):
    """The prompt counts the notes the delete removes, the ones stored on the rows, not every version's notes."""
    mock_resolve_suite.return_value = _make_suite()
    tests = [_make_td_minimal() for _ in range(3)]
    mock_select.return_value = tests
    mock_all_version_notes.return_value = {str(tests[0].id): 5}
    ctx = _confirming_ctx()

    result = asyncio.run(delete_tests(ctx, test_suite_id=str(uuid4())))

    message = ctx.elicit.await_args.args[0]
    assert message.startswith("Delete every test in suite `demo_suite`?")
    assert "- Tests: 3" in message
    assert "- Notes: 2" in message
    assert "Notes deleted:** 2" in result


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_deletes_nothing_when_the_user_declines(mock_list, _mock_notes, mock_delete, db_session_mock):
    mock_list.return_value = [_make_td_minimal()]
    ctx = _confirming_ctx()
    ctx.elicit.return_value = MagicMock(action="decline")

    with pytest.raises(MCPUserError, match="did not confirm"):
        asyncio.run(delete_tests(ctx, test_definition_ids=[str(mock_list.return_value[0].id)]))

    mock_delete.assert_not_called()


@patch.object(TestDefinition, "list_for_ids", return_value=[])
def test_delete_tests_does_not_ask_about_a_request_that_fails(_mock_list, db_session_mock):
    ctx = _confirming_ctx()

    with pytest.raises(MCPUserError, match="not found or not accessible"):
        asyncio.run(delete_tests(ctx, test_definition_ids=[str(uuid4())]))

    ctx.elicit.assert_not_awaited()


@patch.object(TestDefinition, "select_minimal_where", return_value=[])
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_delete_tests_does_not_ask_when_nothing_matched(mock_resolve_suite, _mock_select, db_session_mock):
    mock_resolve_suite.return_value = _make_suite()
    ctx = _confirming_ctx()

    result = asyncio.run(delete_tests(ctx, test_suite_id=str(uuid4()), table_name="absent"))

    assert "No tests matched" in result
    ctx.elicit.assert_not_awaited()


def test_delete_tests_rolls_back_the_planning_pass_before_asking(db_session_mock):
    """Routing a contract's tests can open a draft, which must not outlive a declined confirmation."""
    events = []
    td = _make_td_minimal()
    ctx = _confirming_ctx()
    ctx.elicit.side_effect = lambda *_: events.append("ask") or MagicMock(action="decline")
    db_session_mock.rollback.side_effect = lambda: events.append("rollback")
    with (
        patch.object(TestDefinition, "list_for_ids", return_value=[td]),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=_make_suite()),
        patch.object(
            TestDefinition,
            "resolve_writable",
            side_effect=lambda *_: events.append("route") or (uuid4(), {td.id: td.id}),
        ),
        patch.object(TestDefinitionNote, "count_stored_on", return_value=0),
        pytest.raises(MCPUserError),
    ):
        asyncio.run(delete_tests(ctx, test_definition_ids=[str(td.id)]))

    assert events == ["route", "rollback", "ask"]


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "select_minimal_where")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_delete_tests_deletes_nothing_when_the_selection_changed_while_asking(
    mock_resolve_suite, mock_select, _mock_notes, mock_delete, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    confirmed = _make_td_minimal()
    mock_select.side_effect = [[confirmed], [confirmed, _make_td_minimal()]]

    with pytest.raises(MCPUserError, match="changed while it waited for confirmation"):
        _delete(test_suite_id=str(uuid4()))

    mock_delete.assert_not_called()


@pytest.mark.usefixtures("routes_in_place", "no_pending_tokens")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_without_elicitation_deletes_on_the_second_call_with_the_token(
    mock_list, _mock_notes, mock_delete, db_session_mock
):
    td = _make_td_minimal()
    mock_list.return_value = [td]
    no_elicitation = MagicMock()
    no_elicitation.session.client_params.capabilities.elicitation = None

    with pytest.raises(MCPUserError, match="Confirmation required") as raised:
        asyncio.run(delete_tests(no_elicitation, test_definition_ids=[str(td.id)]))
    mock_delete.assert_not_called()

    token = re.search(r"`confirmation_token` set to `([^`]+)`", str(raised.value)).group(1)
    result = asyncio.run(delete_tests(no_elicitation, test_definition_ids=[str(td.id)], confirmation_token=token))

    assert "Deleted 1 tests" in result
    assert _deleted_ids(mock_delete) == [td.id]


@pytest.mark.usefixtures("routes_in_place", "no_pending_tokens")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_token_does_not_confirm_a_different_selection(
    mock_list, _mock_notes, mock_delete, db_session_mock
):
    first, second = _make_td_minimal(), _make_td_minimal()
    no_elicitation = MagicMock()
    no_elicitation.session.client_params.capabilities.elicitation = None

    mock_list.return_value = [first]
    with pytest.raises(MCPUserError) as raised:
        asyncio.run(delete_tests(no_elicitation, test_definition_ids=[str(first.id)]))
    token = re.search(r"`confirmation_token` set to `([^`]+)`", str(raised.value)).group(1)

    mock_list.return_value = [second]
    with pytest.raises(MCPUserError, match="issued for a different request"):
        asyncio.run(delete_tests(no_elicitation, test_definition_ids=[str(second.id)], confirmation_token=token))

    mock_delete.assert_not_called()


@pytest.mark.usefixtures("no_pending_tokens")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_refuses_a_managed_test_before_asking(mock_list, mock_delete, db_session_mock):
    """The delete would refuse it after the user confirmed; refusing first spares them a prompt that cannot succeed."""
    managed = _make_schema_conformance(table_name="orders")
    mock_list.return_value = [_make_td_minimal(), managed]
    ctx = _confirming_ctx()

    with pytest.raises(MCPUserError) as raised:
        asyncio.run(delete_tests(ctx, test_definition_ids=[str(td.id) for td in mock_list.return_value]))

    message = str(raised.value)
    assert message.startswith("Nothing was deleted. TestGen manages these tests")
    assert f"- Schema Conformance on `orders` (`{managed.id}`)" in message.splitlines()
    ctx.elicit.assert_not_awaited()
    assert not confirmation._pending, "a token was issued for a delete that cannot happen"
    mock_delete.assert_not_called()


def _make_schema_conformance(table_name="orders"):
    td = _make_td_minimal(table_name=table_name, column_name=None, test_type="Schema_Conformance")
    td.test_name_short = "Schema Conformance"
    return td


@pytest.mark.usefixtures("routes_in_place", "no_pending_tokens")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "select_minimal_where")
def test_delete_tests_by_filter_keeps_the_tests_testgen_manages(
    mock_select, _mock_notes, mock_delete, mock_resolve_suite, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    kept = _make_schema_conformance()
    deleted = _make_td_minimal()
    mock_select.return_value = [deleted, kept]
    ctx = _confirming_ctx()

    result = asyncio.run(delete_tests(ctx, test_suite_id=str(uuid4()), table_name="orders"))

    assert _deleted_ids(mock_delete) == [deleted.id]
    assert "Deleted 1 tests" in result
    assert "**Kept, managed by TestGen:** 1" in result
    prompt = ctx.elicit.await_args.args[0]
    assert "Tests: 1" in prompt
    assert "Keeps 1 tests that TestGen manages, such as Schema Conformance." in prompt


@pytest.mark.usefixtures("no_pending_tokens")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinition, "select_minimal_where")
def test_delete_tests_by_filter_matching_only_managed_tests_deletes_nothing(
    mock_select, mock_delete, mock_resolve_suite, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    mock_select.return_value = [_make_schema_conformance()]
    ctx = _confirming_ctx()

    result = asyncio.run(delete_tests(ctx, test_suite_id=str(uuid4()), table_name="orders"))

    assert "# No tests to delete" in result
    assert "TestGen manages the 1 tests that matched" in result
    ctx.elicit.assert_not_awaited()
    mock_delete.assert_not_called()


@pytest.mark.usefixtures("routes_in_place")
@patch.object(TestDefinition, "delete_where")
@patch.object(TestDefinitionNote, "count_stored_on", return_value=0)
@patch.object(TestDefinition, "list_for_ids")
def test_delete_tests_by_ids_names_every_suite_the_tests_belong_to(mock_list, _mock_notes, _mock_delete, db_session_mock):
    """The user reads the prompt in their own client, outside the conversation, so it names what goes."""
    orders, customers = _make_suite(), _make_suite()
    orders.test_suite, customers.test_suite = "orders_suite", "customers_suite"
    mock_list.return_value = [
        _make_td_minimal(test_suite_id=orders.id),
        _make_td_minimal(test_suite_id=customers.id),
        _make_td_minimal(test_suite_id=orders.id),
    ]
    ctx = _confirming_ctx()

    with patch(
        "testgen.mcp.tools.test_definitions.TestSuite.get",
        side_effect={orders.id: orders, customers.id: customers}.get,
    ):
        asyncio.run(delete_tests(ctx, test_definition_ids=[str(td.id) for td in mock_list.return_value]))

    message = ctx.elicit.await_args.args[0]
    assert message.startswith("Delete the named tests across 2 suites: `orders_suite`, `customers_suite`?")
    assert "- Tests: 3" in message


# -- delete_tests: version scoping ---------------------------------------------
#
# These drive the real model methods against a mocked session and assert the SQL that
# reaches it, rather than the clauses the tool hands in — the predicate is applied
# inside ``_scoped_select``, so asserting the arguments would pass with it removed.


@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch("testgen.common.models.entity.get_current_session")
@patch("testgen.common.models.test_definition.get_current_session")
def test_delete_tests_by_suite_selects_only_the_resolved_version(
    mock_td_session, mock_entity_session, mock_resolve_suite, db_session_mock
):
    mock_resolve_suite.return_value = _make_suite()
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = []
    mock_td_session.return_value = session
    mock_entity_session.return_value = session

    _delete(test_suite_id=str(uuid4()))

    selects = [s for s in emitted_statements(session) if str(s).lstrip().lower().startswith("select")]
    assert selects, "the filter path issued no select"
    assert scopes_to_a_version(selects[0]), (
        "the filter path selects every version of the suite's tests, not the one it resolves to"
    )


@pytest.mark.usefixtures("routes_in_place")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
@patch("testgen.mcp.tools.test_definitions.get_current_session")
@patch("testgen.common.models.get_current_session")
@patch("testgen.common.models.entity.get_current_session")
@patch("testgen.common.models.test_definition.get_current_session")
def test_delete_tests_deletes_only_within_the_resolved_version(
    mock_td_session, mock_entity_session, mock_base_session, mock_tool_session, mock_resolve_suite, db_session_mock
):
    """The delete carries the predicate itself, so it stays correct if its ids ever
    start arriving from somewhere unscoped."""
    mock_resolve_suite.return_value = _make_suite()
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = [
        {
            "id": uuid4(),
            "table_groups_id": uuid4(),
            "test_type": "Alpha_Trunc",
            "test_suite_id": uuid4(),
            "schema_name": "demo",
            "table_name": "orders",
            "column_name": "email",
            "test_active": True,
            "lock_refresh": False,
            "test_name_short": "Alpha Truncation",
        }
    ]
    for mock_session in (mock_td_session, mock_entity_session, mock_base_session, mock_tool_session):
        mock_session.return_value = session

    with (
        patch.object(TestDefinitionNote, "count_stored_on", return_value=0),
        patch.object(TestDefinition, "_assert_no_managed_definitions"),
    ):
        _delete(test_suite_id=str(uuid4()))

    deletes = [s for s in emitted_statements(session) if str(s).lstrip().lower().startswith("delete")]
    assert deletes, "no delete was issued"
    assert scopes_to_a_version(deletes[0]), "the delete is not confined to the resolved version"


# -- contract versions --------------------------------------------------------


def _contract_suite():
    suite = _make_suite()
    suite.test_suite = "Orders"
    suite.suite_type = SuiteType.CONTRACT
    return suite


def _summary_row():
    item = _make_td_summary()
    item.last_auto_gen_date = None
    item.flagged = False
    return item


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_suite")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_list_tests_on_a_contract_names_the_resolved_version(mock_resolve, mock_list, mock_notes, db_session_mock):
    suite = _contract_suite()
    mock_resolve.return_value = suite
    mock_list.return_value = ([_summary_row()], 1)
    mock_notes.get_notes_count_by_ids.return_value = {}
    draft = SuiteVersion(id=uuid4(), version=4)
    with patch("testgen.mcp.tools.test_definitions.resolved_version", return_value=draft):
        out = list_tests(str(suite.id))
    assert "**Version:** v4 draft" in out
    assert mock_list.call_args.kwargs["version_id"] is None


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_suite")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_list_tests_with_a_version_reads_that_version(mock_resolve, mock_list, mock_notes, db_session_mock):
    suite = _contract_suite()
    mock_resolve.return_value = suite
    mock_list.return_value = ([_summary_row()], 1)
    mock_notes.get_notes_count_by_ids.return_value = {}
    v2 = SuiteVersion(id=uuid4(), version=2, frozen_at=datetime(2026, 1, 1, tzinfo=UTC))
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_contract_version", return_value=v2),
        patch.object(SuiteVersion, "is_active", return_value=False),
    ):
        out = list_tests(str(suite.id), version=2)
    assert mock_list.call_args.kwargs["version_id"] == v2.id
    assert "**Version:** v2 superseded" in out


@patch("testgen.mcp.tools.test_definitions.TestDefinitionNote")
@patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_suite")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_list_tests_on_a_regular_suite_names_no_version(mock_resolve, mock_list, mock_notes, db_session_mock):
    suite = _contract_suite()
    suite.suite_type = SuiteType.REGULAR
    mock_resolve.return_value = suite
    mock_list.return_value = ([_summary_row()], 1)
    mock_notes.get_notes_count_by_ids.return_value = {}
    out = list_tests(str(suite.id))
    assert "Version" not in out
    assert mock_list.call_args.kwargs["version_id"] is None


@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_list_tests_with_a_version_on_a_regular_suite_is_refused(mock_resolve, db_session_mock):
    suite = _contract_suite()
    suite.suite_type = SuiteType.REGULAR
    mock_resolve.return_value = suite
    with pytest.raises(MCPUserError, match="is not a contract"):
        list_tests(str(suite.id), version=1)


def test_get_test_on_a_contract_names_the_version_its_row_belongs_to(db_session_mock):
    row = _summary_row()
    row.version_id = uuid4()
    version = SuiteVersion(id=row.version_id, version=3, frozen_at=datetime(2026, 9, 12, tzinfo=UTC))
    with (
        patch("testgen.mcp.tools.test_definitions.TestDefinition.get_for_project", return_value=row),
        patch("testgen.mcp.tools.test_definitions.TestDefinitionNote.get_notes", return_value=[]),
        patch("testgen.mcp.tools.test_definitions.TestResult.select_history", return_value=[]) as history,
        patch.object(SuiteVersion, "get", return_value=version),
        patch.object(SuiteVersion, "is_active", return_value=True),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=_contract_suite()),
    ):
        out = get_test(str(row.id))
    assert "**Version:** v3 active" in out
    assert out.index("**ID:**") < out.index("**Version:**") < out.index("**Test Type:**")
    assert SuiteType.CONTRACT in history.call_args.kwargs["suite_types"]


@patch("testgen.mcp.tools.test_definitions.export_definitions")
@patch("testgen.mcp.tools.test_definitions.resolve_test_suite")
def test_export_tests_with_a_version_exports_that_version(mock_resolve, mock_export, db_session_mock):
    suite = _contract_suite()
    mock_resolve.return_value = suite
    mock_export.return_value = _make_export_document()
    v3 = SuiteVersion(id=uuid4(), version=3, frozen_at=datetime(2026, 9, 12, tzinfo=UTC))
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_contract_version", return_value=v3),
        patch.object(SuiteVersion, "is_active", return_value=True),
    ):
        out = export_tests(str(suite.id), version=3)
    assert mock_export.call_args.kwargs["version_id"] == v3.id
    assert "**Version:** v3 active" in out


# -- contract versions: writes ------------------------------------------------


def _orm_td(**attrs):
    td = _make_td_orm()
    td.table_groups_id = uuid4()
    for key, value in attrs.items():
        setattr(td, key, value)
    return td


@contextmanager
def _update_context(td, suite, versions=None, old_version=None, old_state="active"):
    """Patch what ``update_test`` reads around the row, keyed to the version the row starts in."""
    original = td.version_id
    frozen = SuiteVersion(id=original, version=old_version, frozen_at=datetime(2026, 9, 12, tzinfo=UTC))
    known = {original: frozen, **(versions or {})}
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_definition", return_value=td),
        patch("testgen.mcp.tools.test_definitions.TestType.get", return_value=_make_test_type()),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TableGroup.get", return_value=None),
        patch.object(SuiteVersion, "get", side_effect=lambda version_id: known.get(version_id)),
        patch.object(
            SuiteVersion,
            "is_active",
            side_effect=lambda version_id, _suite_id: version_id == original and old_state == "active",
        ),
    ):
        yield


def test_update_routed_to_the_draft_returns_the_new_id_and_names_the_draft(db_session_mock):
    old_id, new_id = uuid4(), uuid4()
    td = _orm_td(id=old_id, version_id=uuid4())
    draft = SuiteVersion(id=uuid4(), version=4)

    def _route():
        td.id, td.version_id = new_id, draft.id

    td.save.side_effect = _route
    with _update_context(td, suite=_contract_suite(), versions={draft.id: draft}, old_version=3):
        out = update_test(str(old_id), fields={"severity": "Fail"})
    assert f"`{new_id}`" in out
    assert f"was `{old_id}`, in v3 active" in out
    assert "use the new ID from now on" in out
    assert "**Version:** v4 draft" in out


def test_update_by_an_active_id_applies_the_fields_to_the_drafts_copy(db_session_mock):
    active_version, draft = uuid4(), SuiteVersion(id=uuid4(), version=4)
    active = _orm_td(id=uuid4(), version_id=active_version, severity="Fail", threshold_value="50")
    copy = _orm_td(id=uuid4(), version_id=draft.id, severity="Log", threshold_value="99")
    rows = {active.id: active, copy.id: copy}
    with (
        _update_context(active, suite=_contract_suite(), versions={draft.id: draft}, old_version=3),
        patch(
            "testgen.mcp.tools.test_definitions.resolve_test_definition",
            side_effect=lambda row_id: rows[UUID(row_id)],
        ),
        patch.object(TestDefinition, "resolve_writable", return_value=(draft.id, {active.id: copy.id})),
    ):
        out = update_test(str(active.id), fields={"severity": "Warning"})

    assert copy.severity == "Warning"
    assert copy.threshold_value == "99"
    copy.save.assert_called_once()
    assert active.severity == "Fail"
    active.save.assert_not_called()
    assert "| `severity` | Log | Warning |" in out
    assert f"`{copy.id}` (was `{active.id}`, in v3 active" in out
    assert "**Version:** v4 draft" in out


def test_update_of_a_draft_row_names_the_draft_without_a_new_id(db_session_mock):
    draft = SuiteVersion(id=uuid4(), version=4)
    td = _orm_td(id=uuid4(), version_id=draft.id)
    with _update_context(td, suite=_contract_suite(), versions={draft.id: draft}):
        out = update_test(str(td.id), fields={"severity": "Fail"})
    assert "**Version:** v4 draft" in out
    assert "was `" not in out


def test_update_of_a_test_the_draft_removed_names_the_draft(db_session_mock):
    td = _orm_td(id=uuid4(), version_id=uuid4())
    draft = SuiteVersion(id=uuid4(), version=4)
    td.save.side_effect = RemovedInDraftError(draft.id, [td.id])
    with (
        _update_context(td, suite=_contract_suite(), versions={draft.id: draft}, old_version=3),
        pytest.raises(MCPUserError, match=rf"Test `{td.id}` was removed in v4 draft of contract `Orders`"),
    ):
        update_test(str(td.id), fields={"severity": "Fail"})


def test_update_with_an_id_the_model_refuses_names_the_version(db_session_mock):
    td = _orm_td(id=uuid4(), version_id=uuid4())
    td.save.side_effect = FrozenVersionError(td.version_id)
    with (
        _update_context(td, suite=_contract_suite(), old_version=2, old_state="superseded"),
        pytest.raises(
            MCPUserError,
            match=rf"Test `{td.id}` belongs to v2 superseded of contract `Orders`, which can no longer be edited",
        ),
    ):
        update_test(str(td.id), fields={"severity": "Fail"})


def test_update_of_an_active_test_the_draft_cannot_match_says_so(db_session_mock):
    td = _orm_td(id=uuid4(), version_id=uuid4())
    draft = SuiteVersion(id=uuid4(), version=4)
    td.save.side_effect = UnmatchedInDraftError(td.version_id, draft.id, [td.id])
    with (
        _update_context(td, suite=_contract_suite(), versions={draft.id: draft}, old_version=3),
        pytest.raises(
            MCPUserError,
            match=rf"Test `{td.id}` in v3 active of contract `Orders` cannot be matched to its copy in v4 draft",
        ),
    ):
        update_test(str(td.id), fields={"severity": "Fail"})


def test_delete_of_active_tests_the_draft_cannot_match_names_only_those(db_session_mock):
    suite = _contract_suite()
    matched_id, unmatched_id = uuid4(), uuid4()
    active = SuiteVersion(id=uuid4(), version=3, frozen_at=datetime(2026, 1, 1, tzinfo=UTC))
    draft = SuiteVersion(id=uuid4(), version=4)
    with (
        patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_ids", return_value=[
            MagicMock(id=matched_id, test_suite_id=suite.id), MagicMock(id=unmatched_id, test_suite_id=suite.id),
        ]),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable",
              side_effect=UnmatchedInDraftError(active.id, draft.id, [unmatched_id])),
        patch.object(SuiteVersion, "get", side_effect={active.id: active, draft.id: draft}.get),
        patch.object(SuiteVersion, "is_active", return_value=True),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.delete_where") as delete_where,
        pytest.raises(
            MCPUserError,
            match=rf"^Test `{unmatched_id}` in v3 active of contract `Orders` cannot be matched to its copy in "
            r"v4 draft, so it cannot be edited\. Use `list_tests` to find the draft's tests\.$",
        ),
    ):
        _delete(test_definition_ids=[str(matched_id), str(unmatched_id)])
    delete_where.assert_not_called()


def test_update_on_a_regular_suite_names_no_version(db_session_mock):
    td = _orm_td(id=uuid4(), version_id=uuid4())
    suite = _contract_suite()
    suite.suite_type = SuiteType.REGULAR
    with _update_context(td, suite=suite):
        out = update_test(str(td.id), fields={"severity": "Warning"})
    assert "Version" not in out
    assert "was `" not in out


def test_update_holds_its_edits_out_of_autoflush_until_save(db_session_mock):
    """A query between the edit and ``save`` must not flush the edit onto a frozen row before
    ``save`` can move it to the draft."""
    td = _orm_td(id=uuid4(), version_id=uuid4(), severity="Fail")
    draft = SuiteVersion(id=uuid4(), version=4)
    events = []
    db_session_mock.no_autoflush.__enter__.side_effect = lambda *_: events.append("hold")
    db_session_mock.no_autoflush.__exit__.side_effect = lambda *_: events.append("release")
    td.save.side_effect = lambda: events.append("save")
    with (
        _update_context(td, suite=_contract_suite(), versions={draft.id: draft}, old_version=3),
        patch(
            "testgen.mcp.tools.test_definitions.TableGroup.get",
            side_effect=lambda _id: events.append(f"query after edit to {td.severity}"),
        ),
    ):
        update_test(str(td.id), fields={"severity": "Warning"})
    assert events == ["hold", "query after edit to Warning", "release", "save"]


def test_create_on_a_contract_names_the_version_it_landed_in(db_session_mock):
    suite = _contract_suite()
    draft = SuiteVersion(id=uuid4(), version=4)
    saved = MagicMock(id=uuid4(), version_id=draft.id)
    saved.editable_fields.return_value = {"severity", "threshold_value", "column_name"}
    summary = _make_td_summary()
    summary.id, summary.test_suite_id, summary.version_id = saved.id, suite.id, draft.id
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.resolve_test_type", return_value="Alpha_Trunc"),
        patch("testgen.mcp.tools.test_definitions.TestType.get", return_value=_make_test_type()),
        patch("testgen.mcp.tools.test_definitions.TableGroup.get", return_value=_make_table_group()),
        patch("testgen.mcp.tools.test_definitions.check_table_declared"),
        patch("testgen.mcp.tools.test_definitions.TestDefinition") as td_cls,
        patch("testgen.mcp.tools.test_definitions.TestDefinitionNote.get_notes", return_value=[]),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch.object(SuiteVersion, "get", side_effect=lambda version_id: draft if version_id == draft.id else None),
        patch.object(SuiteVersion, "is_active", return_value=False),
    ):
        td_cls.return_value = saved
        td_cls.get_for_project.return_value = summary
        out = create_test(
            str(suite.id), "Alpha Truncation", "orders", fields={"column_name": "email", "threshold_value": "64"}
        )
    assert "**Version:** v4 draft" in out
    assert out.count("**Version:**") == 1


def test_delete_by_an_active_version_id_deletes_the_drafts_copy(db_session_mock):
    suite = _contract_suite()
    active_id, copy_id, draft = uuid4(), uuid4(), SuiteVersion(id=uuid4(), version=4)
    selected = MagicMock(id=active_id, test_suite_id=suite.id, test_name_short="Row Count",
                         test_type="Row_Ct", table_name="orders", column_name=None)
    with (
        patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_ids", return_value=[selected]),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable",
              return_value=(draft.id, {active_id: copy_id})) as route,
        patch("testgen.mcp.tools.test_definitions.SuiteVersion.get", return_value=draft),
        patch("testgen.mcp.tools.test_definitions.TestDefinitionNote.count_stored_on", return_value=0),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.delete_where") as delete_where,
    ):
        out = _delete(test_definition_ids=[str(active_id)])
    route.assert_called_with(suite.id, [active_id])
    sql = str(delete_where.call_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))
    assert str(copy_id) in sql and str(active_id) not in sql
    assert f"`{copy_id}`" in out
    assert "**Version:** v4 draft" in out


def test_delete_naming_an_active_id_and_its_drafts_copy_deletes_and_counts_the_copy_once(db_session_mock):
    suite = _contract_suite()
    active_id, copy_id, draft = uuid4(), uuid4(), SuiteVersion(id=uuid4(), version=4)
    rows = [
        MagicMock(id=row_id, test_suite_id=suite.id, test_name_short="Row Count",
                  test_type="Row_Ct", table_name="orders", column_name=None)
        for row_id in (active_id, copy_id)
    ]
    with (
        patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_ids", return_value=rows),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable",
              return_value=(draft.id, {active_id: copy_id, copy_id: copy_id})),
        patch("testgen.mcp.tools.test_definitions.SuiteVersion.get", return_value=draft),
        patch(
            "testgen.mcp.tools.test_definitions.TestDefinitionNote.count_stored_on", return_value=0
        ) as notes,
        patch("testgen.mcp.tools.test_definitions.TestDefinition.delete_where"),
    ):
        out = _delete(test_definition_ids=[str(active_id), str(copy_id)])
    assert "# Deleted 1 tests" in out
    assert out.count(f"`{copy_id}`") == 1
    assert notes.call_args.args[0] == [copy_id]


def test_delete_of_a_test_the_draft_removed_deletes_nothing(db_session_mock):
    suite = _contract_suite()
    active_id, draft = uuid4(), SuiteVersion(id=uuid4(), version=4)
    selected = MagicMock(id=active_id, test_suite_id=suite.id)
    with (
        patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_ids", return_value=[selected]),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable",
              side_effect=RemovedInDraftError(draft.id, [active_id])),
        patch("testgen.mcp.tools.test_definitions.SuiteVersion.get", return_value=draft),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.delete_where") as delete_where,
        pytest.raises(MCPUserError, match=rf"Test `{active_id}` was removed in v4 draft of contract `Orders`"),
    ):
        _delete(test_definition_ids=[str(active_id)])
    delete_where.assert_not_called()


def test_delete_by_a_superseded_version_id_names_the_version(db_session_mock):
    suite = _contract_suite()
    old_id = uuid4()
    v2 = SuiteVersion(id=uuid4(), version=2, frozen_at=datetime(2026, 1, 1, tzinfo=UTC))
    with (
        patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_ids",
              return_value=[MagicMock(id=old_id, test_suite_id=suite.id)]),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable",
              side_effect=FrozenVersionError(v2.id)),
        patch.object(SuiteVersion, "get", return_value=v2),
        patch.object(SuiteVersion, "is_active", return_value=False),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.delete_where") as delete_where,
        pytest.raises(
            MCPUserError,
            match=rf"Test `{old_id}` belongs to v2 superseded of contract `Orders`, which can no longer be edited",
        ),
    ):
        _delete(test_definition_ids=[str(old_id)])
    delete_where.assert_not_called()


def test_delete_spanning_suites_routes_every_suite_before_deleting_any(db_session_mock):
    regular, contract = _make_suite(), _contract_suite()
    regular_id, contract_id, draft = uuid4(), uuid4(), SuiteVersion(id=uuid4(), version=4)
    rows = [MagicMock(id=regular_id, test_suite_id=regular.id), MagicMock(id=contract_id, test_suite_id=contract.id)]

    def _route(suite_id, row_ids):
        if suite_id == contract.id:
            raise RemovedInDraftError(draft.id, row_ids)
        return uuid4(), {row_id: row_id for row_id in row_ids}

    with (
        patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_ids", return_value=rows),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get",
              side_effect=lambda suite_id: {regular.id: regular, contract.id: contract}[suite_id]),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable", side_effect=_route) as route,
        patch("testgen.mcp.tools.test_definitions.SuiteVersion.get", return_value=draft),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.delete_where") as delete_where,
        pytest.raises(MCPUserError, match=rf"Test `{contract_id}` was removed in v4 draft"),
    ):
        _delete(test_definition_ids=[str(regular_id), str(contract_id)])
    assert [call.args for call in route.call_args_list] == [(regular.id, [regular_id]), (contract.id, [contract_id])]
    delete_where.assert_not_called()


def test_delete_by_suite_filter_routes_the_selection_to_the_draft(db_session_mock):
    suite = _contract_suite()
    active_id, copy_id, draft = uuid4(), uuid4(), SuiteVersion(id=uuid4(), version=4)
    selected = _make_td_minimal(test_id=active_id)
    selected.test_suite_id = suite.id
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.select_minimal_where", return_value=[selected]),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable",
              return_value=(draft.id, {active_id: copy_id})) as route,
        patch("testgen.mcp.tools.test_definitions.SuiteVersion.get", return_value=draft),
        patch("testgen.mcp.tools.test_definitions.TestDefinitionNote.count_stored_on", return_value=0),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.delete_where") as delete_where,
    ):
        out = _delete(test_suite_id=str(suite.id))
    route.assert_called_with(suite.id, [active_id])
    assert _deleted_ids(delete_where) == [copy_id]
    assert f"`{copy_id}`" in out
    assert "**Version:** v4 draft" in out


def test_delete_by_suite_filter_matching_nothing_opens_no_draft(db_session_mock):
    suite = _contract_suite()
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.select_minimal_where", return_value=[]),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable") as route,
    ):
        out = _delete(test_suite_id=str(suite.id))
    route.assert_not_called()
    assert "No tests matched" in out


def test_bulk_update_routes_the_matched_tests_to_the_draft(db_session_mock):
    suite = _contract_suite()
    matched, copy_id, draft = uuid4(), uuid4(), SuiteVersion(id=uuid4(), version=4)
    db_session_mock.execute.return_value.all.return_value = [_matched_row(matched)]
    db_session_mock.execute.return_value.rowcount = 1
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable",
              return_value=(draft.id, {matched: copy_id})) as route,
        patch("testgen.mcp.tools.test_definitions.SuiteVersion.get", return_value=draft),
    ):
        out = bulk_update_tests(test_suite_id=str(suite.id), action="disable")
    route.assert_called_once_with(suite.id, [matched])
    sql = str(db_session_mock.execute.call_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))
    assert str(copy_id) in sql and str(matched) not in sql
    assert "Disabled 1 tests in suite `Orders`" in out
    assert "**Version:** v4 draft" in out


@patch("testgen.mcp.tools.test_definitions._set_test_values")
@patch.object(TestDefinition, "list_for_ids")
def test_bulk_update_tests_by_ids_routes_to_the_draft_and_counts_each_row_once(mock_list, mock_set, db_session_mock):
    suite = _contract_suite()
    in_force, draft_copy, draft = uuid4(), uuid4(), SuiteVersion(id=uuid4(), version=4)
    named = [_make_td_minimal(test_id=in_force), _make_td_minimal(test_id=draft_copy)]
    for td in named:
        td.test_suite_id = suite.id
    mock_list.return_value = named
    with (
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch.object(
            TestDefinition, "resolve_writable", return_value=(draft.id, {in_force: draft_copy, draft_copy: draft_copy})
        ),
        patch("testgen.mcp.tools.test_definitions.SuiteVersion.get", return_value=draft),
    ):
        out = bulk_update_tests(action="disable", test_definition_ids=[str(in_force), str(draft_copy)])

    assert mock_set.call_args.args[0] == [draft_copy]
    assert "Disabled 1 tests" in out
    assert "**Version:** v4 draft" in out


def test_bulk_update_matching_nothing_opens_no_draft(db_session_mock):
    suite = _contract_suite()
    db_session_mock.execute.return_value.all.return_value = []
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable") as route,
    ):
        out = bulk_update_tests(test_suite_id=str(suite.id), action="disable")
    route.assert_not_called()
    assert "No tests matched" in out


def test_import_on_a_contract_names_the_version_written(db_session_mock):
    from testgen.common.test_definition_export_import_service import ContractVersion

    suite = _contract_suite()
    response = _make_import_response(created=2, version=ContractVersion(number=4, state=VersionState.DRAFT))
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.import_definitions", return_value=response),
    ):
        out = import_tests(str(suite.id), payload='{"definitions": []}', mode="apply")
    assert "**Version:** v4 draft" in out


def test_import_into_a_regular_suite_names_no_version(db_session_mock):
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=_make_suite()),
        patch("testgen.mcp.tools.test_definitions.import_definitions", return_value=_make_import_response(created=2)),
    ):
        out = import_tests(str(uuid4()), payload='{"definitions": []}', mode="apply")
    assert "Version" not in out


def test_import_naming_a_frozen_version_is_a_user_error(db_session_mock):
    suite = _contract_suite()
    v2 = SuiteVersion(id=uuid4(), version=2, frozen_at=datetime(2026, 1, 1, tzinfo=UTC))
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.import_definitions", side_effect=FrozenVersionError(v2.id)),
        patch.object(SuiteVersion, "get", return_value=v2),
        patch.object(SuiteVersion, "is_active", return_value=False),
        pytest.raises(
            MCPUserError, match=r"v2 superseded of contract `Orders` can no longer be edited\. Nothing was applied\."
        ),
    ):
        import_tests(str(suite.id), payload='{"definitions": []}', mode="apply")


def test_import_naming_an_active_test_the_draft_cannot_match_says_so(db_session_mock):
    suite = _contract_suite()
    unmatched = uuid4()
    active = SuiteVersion(id=uuid4(), version=3, frozen_at=datetime(2026, 1, 1, tzinfo=UTC))
    draft = SuiteVersion(id=uuid4(), version=4)
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch(
            "testgen.mcp.tools.test_definitions.import_definitions",
            side_effect=UnmatchedInDraftError(active.id, draft.id, [unmatched]),
        ),
        patch.object(SuiteVersion, "get", side_effect={active.id: active, draft.id: draft}.get),
        patch.object(SuiteVersion, "is_active", return_value=True),
        pytest.raises(
            MCPUserError,
            match=rf"^Test `{unmatched}` in v3 active of contract `Orders` cannot be matched to its copy in "
            r"v4 draft, so it cannot be edited\. Use `list_tests` to find the draft's tests\. Nothing was applied\.$",
        ),
    ):
        import_tests(str(suite.id), payload='{"definitions": []}', mode="apply")


def test_import_naming_a_test_the_draft_removed_is_a_user_error(db_session_mock):
    suite = _contract_suite()
    removed, draft = uuid4(), SuiteVersion(id=uuid4(), version=4)
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch(
            "testgen.mcp.tools.test_definitions.import_definitions",
            side_effect=RemovedInDraftError(draft.id, [removed]),
        ),
        patch.object(SuiteVersion, "get", return_value=draft),
        pytest.raises(MCPUserError, match=rf"Test `{removed}` was removed in v4 draft of contract `Orders`\. Nothing was applied\.$"),
    ):
        import_tests(str(suite.id), payload='{"definitions": []}', mode="apply")


def test_import_whose_target_vanished_is_a_user_error(db_session_mock):
    suite = _contract_suite()
    gone = uuid4()
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch(
            "testgen.mcp.tools.test_definitions.import_definitions",
            side_effect=ValueError(f"Test definition {gone} no longer exists."),
        ),
        pytest.raises(MCPUserError, match=rf"Test definition {gone} no longer exists\. Nothing was applied\."),
    ):
        import_tests(str(suite.id), payload='{"definitions": []}', mode="apply")


def test_import_on_a_regular_suite_names_no_version(db_session_mock):
    suite = _contract_suite()
    suite.suite_type = SuiteType.REGULAR
    with (
        patch("testgen.mcp.tools.test_definitions.resolve_test_suite", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.import_definitions", return_value=_make_import_response(created=2)),
    ):
        out = import_tests(str(suite.id), payload='{"definitions": []}', mode="apply")
    assert "Version" not in out


def test_delete_naming_several_tests_lists_only_those_of_the_refused_version(db_session_mock):
    suite = _contract_suite()
    old_id, current_id = uuid4(), uuid4()
    v2 = SuiteVersion(id=uuid4(), version=2, frozen_at=datetime(2026, 1, 1, tzinfo=UTC))
    db_session_mock.scalars.return_value.all.return_value = [old_id]
    rows = [MagicMock(id=old_id, test_suite_id=suite.id), MagicMock(id=current_id, test_suite_id=suite.id)]
    with (
        patch("testgen.mcp.tools.test_definitions.TestDefinition.list_for_ids", return_value=rows),
        patch("testgen.mcp.tools.test_definitions.TestSuite.get", return_value=suite),
        patch("testgen.mcp.tools.test_definitions.TestDefinition.resolve_writable",
              side_effect=FrozenVersionError(v2.id)),
        patch.object(SuiteVersion, "get", return_value=v2),
        patch.object(SuiteVersion, "is_active", return_value=False),
        pytest.raises(MCPUserError) as refusal,
    ):
        _delete(test_definition_ids=[str(old_id), str(current_id)])
    assert f"Test `{old_id}` belongs to v2 superseded" in str(refusal.value)
    assert str(current_id) not in str(refusal.value)
    lookup = db_session_mock.scalars.call_args.args[0]
    assert any(
        equality_conjunct(term, "version_id", "test_definitions", v2.id) for term in conjuncts(lookup.whereclause)
    )


def test_resolved_version_is_the_contract_services_default_version():
    suite, target = MagicMock(suite_type=SuiteType.CONTRACT), MagicMock()
    with patch("testgen.mcp.tools.test_definitions.contract_service.version_for_export", return_value=target) as rule:
        assert resolved_version(suite) is target
    rule.assert_called_once_with(suite)


def test_resolved_version_is_none_for_a_regular_suite():
    assert resolved_version(MagicMock(suite_type=SuiteType.REGULAR)) is None


def test_resolved_version_reports_a_contract_with_no_version_to_read():
    with (
        patch(
            "testgen.mcp.tools.test_definitions.contract_service.version_for_export",
            side_effect=ValueError("This contract has no version to export."),
        ),
        pytest.raises(MCPUserError, match="no version to export"),
    ):
        resolved_version(MagicMock(suite_type=SuiteType.CONTRACT))


def _value_list_td(baseline_value: str) -> MagicMock:
    td = _orm_td(test_type="LOV_Match", baseline_value=baseline_value, table_name="orders", column_name="qty")
    td.editable_fields.return_value = td.editable_fields.return_value | {"baseline_value"}
    return td


@patch("testgen.mcp.tools.test_definitions.DataColumnChars.general_type_of", return_value="N")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_saves_nothing_for_a_list_that_dedupes_to_the_stored_one(
    mock_resolve_td, mock_tt_model, _mock_general_type, db_session_mock
):
    td = _value_list_td("1,2")
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    result = update_test(str(td.id), fields={"baseline_value": "1, 2,1.00"})

    assert "No fields changed" in result
    td.save.assert_not_called()


@patch("testgen.mcp.tools.test_definitions.DataColumnChars.general_type_of", return_value="N")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_stores_a_list_without_duplicates(mock_resolve_td, mock_tt_model, _mock_general_type, db_session_mock):
    td = _value_list_td("1,2")
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    update_test(str(td.id), fields={"baseline_value": "3,1.5,3.0"})

    assert td.baseline_value == "3,1.5"
    td.save.assert_called_once()


@patch("testgen.mcp.tools.test_definitions.DataColumnChars.general_type_of", return_value="N")
@patch("testgen.mcp.tools.test_definitions.TestType")
@patch("testgen.mcp.tools.test_definitions.resolve_test_definition")
def test_update_test_rejects_a_non_number_listed_for_a_numeric_column(
    mock_resolve_td, mock_tt_model, _mock_general_type, db_session_mock
):
    td = _value_list_td("1,2")
    mock_resolve_td.return_value = td
    mock_tt_model.get.return_value = _make_test_type()

    with pytest.raises(MCPUserError) as error:
        update_test(str(td.id), fields={"baseline_value": "1,two"})

    assert str(error.value) == (
        "Update rejected. No changes saved.\n\n- `baseline_value`: contains a value that is not a number: two"
    )
    td.save.assert_not_called()
