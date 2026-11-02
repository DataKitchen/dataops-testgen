"""Audit records of the UI's test results, hygiene issues, and metadata import."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import Disposition
from testgen.common.test_result_disposition_service import DispositionUpdate
from testgen.ui.views import hygiene_issues, test_results
from testgen.ui.views.dialogs import import_metadata_dialog

pytestmark = pytest.mark.unit


def test_a_hygiene_disposition_records_the_previous_values_the_update_returned():
    issue = uuid4()
    session = MagicMock()
    session.execute.return_value = iter([SimpleNamespace(id=issue, disposition="Confirmed")])
    with (
        patch.object(hygiene_issues, "get_current_session", return_value=session),
        patch.object(hygiene_issues, "record_issue_dispositions") as record,
    ):
        hygiene_issues._update_anomaly_disposition([str(issue)], "No Decision")

    assert "RETURNING r.id, r.disposition" in str(session.execute.call_args.args[0])
    session.commit.assert_not_called()
    record.assert_called_once_with({issue: "Confirmed"}, None)


def test_a_test_result_disposition_records_what_the_update_changed():
    update = DispositionUpdate(matched=1, passed_skipped=0)
    with (
        patch.object(test_results, "set_test_results_disposition", return_value=update) as write,
        patch.object(test_results, "record_result_dispositions") as record,
    ):
        assert test_results.update_result_disposition(["r1"], "Inactive") is update

    write.assert_called_once_with(["r1"], Disposition.INACTIVE)
    record.assert_called_once_with(update, Disposition.INACTIVE)


def test_a_metadata_import_records_the_entries_it_changed_as_one_act():
    table, column = MagicMock(), MagicMock()
    preview = {
        "metadata_columns": ["description"],
        "table_rows": [{"table_id": "t1", "description": "Orders"}],
        "column_rows": [{"column_id": "c1", "description": "Total"}],
    }
    with (
        patch.object(import_metadata_dialog, "_build_metadata_fields", return_value={"description": "x"}),
        patch.object(import_metadata_dialog.DataTable, "get", return_value=table),
        patch.object(import_metadata_dialog.DataColumnChars, "get", return_value=column),
        patch.object(import_metadata_dialog, "apply_table_metadata"),
        patch.object(import_metadata_dialog, "apply_column_metadata"),
        patch.object(import_metadata_dialog, "record_catalog_changes") as record,
    ):
        import_metadata_dialog.apply_metadata_import(preview)

    record.assert_called_once_with([table, column])
