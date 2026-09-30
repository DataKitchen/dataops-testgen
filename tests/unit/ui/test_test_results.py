from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from testgen.common.models.test_definition import MISSING_TEST_DEFINITION_MESSAGE
from testgen.ui.views.test_results import (
    _build_edit_test_dialog_data,
    _build_test_definition_data,
    _load_notes_dialog_data,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.views.test_results"


def test_build_edit_test_dialog_data_without_id_returns_nothing():
    assert _build_edit_test_dialog_data(None, MagicMock()) is None


def test_build_edit_test_dialog_data_reports_a_deleted_definition():
    with patch(f"{MODULE}.select_test_definitions_where", return_value=[]):
        data = _build_edit_test_dialog_data("cfa5ef26-0000-0000-0000-000000000000", MagicMock())

    assert data == {"open": True, "error": MISSING_TEST_DEFINITION_MESSAGE}


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
        patch(f"{MODULE}.get_test_definition", return_value=_referential_definition()),
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
