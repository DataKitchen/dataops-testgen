from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from testgen.common.enums import SuiteType
from testgen.common.models.test_definition import MISSING_TEST_DEFINITION_MESSAGE, TestDefinitionSummary
from testgen.ui.queries import test_result_queries
from testgen.ui.services.test_definition_service import MANAGED_EDIT_MESSAGE
from testgen.ui.views.test_results import (
    _build_edit_test_dialog_data,
    _build_test_definition_data,
    _load_notes_dialog_data,
)
from tests.unit.ui.test_test_results_contracts import _render

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.views.test_results"


def test_build_edit_test_dialog_data_without_id_returns_nothing():
    assert _build_edit_test_dialog_data(None, MagicMock()) is None


def test_build_edit_test_dialog_data_reports_a_deleted_definition():
    with patch(f"{MODULE}.select_test_definitions_where", return_value=[]):
        data = _build_edit_test_dialog_data("cfa5ef26-0000-0000-0000-000000000000", MagicMock())

    assert data == {"open": True, "error": MISSING_TEST_DEFINITION_MESSAGE}


def test_build_edit_test_dialog_data_refuses_a_managed_definition():
    with patch(f"{MODULE}.select_test_definitions_where", return_value=[MagicMock(test_type="Schema_Conformance")]):
        data = _build_edit_test_dialog_data("cfa5ef26-0000-0000-0000-000000000000", MagicMock())

    assert data == {"open": True, "error": MANAGED_EDIT_MESSAGE}



def test_build_edit_test_dialog_data_lists_the_catalog_tables():
    row = SimpleNamespace(**dict.fromkeys(TestDefinitionSummary.columns()))
    row.test_type, row.table_name = "Row_Ct", "orders"
    columns = [{"table_name": "orders", "column_name": "id"}, {"table_name": "customers", "column_name": "id"}]
    with (
        patch(f"{MODULE}.select_test_definitions_where", return_value=[row]),
        patch(f"{MODULE}.get_test_suite", return_value=MagicMock(suite_type=SuiteType.REGULAR)),
        patch(f"{MODULE}.get_table_group_minimal"),
        patch(f"{MODULE}.get_connection", return_value=None),
        patch("testgen.ui.views.test_definitions.get_columns", return_value=columns),
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query"),
        patch("testgen.ui.services.test_definition_service.writable_tables", return_value=None),
    ):
        data = _build_edit_test_dialog_data("cfa5ef26-0000-0000-0000-000000000000", MagicMock())

    assert data["catalog_tables"] == ["customers", "orders"]
    assert data["table_columns"] == columns

def test_load_notes_dialog_data_carries_the_error_and_draft():
    df = pd.DataFrame([{
        "test_definition_id": "cfa5ef26-0000-0000-0000-000000000000",
        "table_name": "orders",
        "column_names": "total",
        "test_name_short": "Row Count",
    }])
    with patch(f"{MODULE}.TestDefinitionNote.get_notes", return_value=[]), patch(f"{MODULE}.session"):
        data = _load_notes_dialog_data(
            "cfa5ef26-0000-0000-0000-000000000000",
            df,
            error=MISSING_TEST_DEFINITION_MESSAGE,
            draft="my unsaved note",
        )

    assert data["error"] == MISSING_TEST_DEFINITION_MESSAGE
    assert data["draft"] == "my unsaved note"


def test_load_notes_dialog_data_has_no_error_by_default():
    with patch(f"{MODULE}.TestDefinitionNote.get_notes", return_value=[]), patch(f"{MODULE}.session"):
        data = _load_notes_dialog_data(
            "cfa5ef26-0000-0000-0000-000000000000",
            pd.DataFrame(columns=["test_definition_id"]),
        )

    assert data["error"] is None
    assert data["draft"] == ""


def _referential_definition() -> MagicMock:
    return MagicMock(
        default_parm_prompts="Reference Schema Name,Reference Table Name",
        default_parm_columns="match_schema_name,match_table_name",
        default_parm_help="",
        match_schema_name="main",
        match_table_name="customers",
        last_manual_update=datetime(2026, 9, 23, 17, 47, 18),
    )


def _definition_data(qualifies_table_refs: bool) -> dict:
    with (
        patch(f"{MODULE}.TestDefinition.get_for_project", return_value=_referential_definition()),
        patch(f"{MODULE}.table_group_qualifies_table_refs", return_value=qualifies_table_refs),
        patch(f"{MODULE}.schema_label_for_table_group", return_value=None),
    ):
        return _build_test_definition_data("cfa5ef26-0000-0000-0000-000000000000", MagicMock())


@pytest.mark.parametrize(
    ("qualifies_table_refs", "expected_labels"),
    (
        (True, ["Reference Schema Name", "Reference Table Name"]),
        (False, ["Reference Table Name"]),
    ),
)
def test_build_test_definition_data_shows_reference_schema_only_where_refs_qualify(
    qualifies_table_refs, expected_labels
):
    data = _definition_data(qualifies_table_refs)

    assert [attribute["label"] for attribute in data["attributes"]] == expected_labels


def test_build_test_definition_data_sends_last_manual_update_as_utc_epoch():
    assert _definition_data(True)["last_manual_update"] == 1790185638


@pytest.mark.parametrize("managed_only", [False, True])
def test_results_count_narrows_to_managed_test_types_on_request(managed_only):
    with patch.object(test_result_queries, "fetch_one_from_db", return_value={"cnt": 2}) as fetch:
        count = test_result_queries.get_test_results_count.__wrapped__("run-1", managed_only=managed_only)

    query, params = fetch.call_args.args
    assert count == 2
    assert ("AND r.test_type IN :managed_test_types" in query) is managed_only
    assert params.get("managed_test_types") == (("Schema_Conformance",) if managed_only else None)


def test_the_results_page_sends_the_managed_count_for_the_filter():
    data = _render(SuiteType.REGULAR)["data"]
    assert data["managed_count"] == 0
