"""On the results page, a contract run's Flag and Edit are disabled and refused writes become a toast."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pandas as pd
import pytest

from testgen.common.enums import JobStatus, SuiteType
from testgen.common.models.suite_version import FrozenVersionError, RemovedInDraftError, UnmatchedInDraftError
from testgen.common.models.test_run import TestRunSummary
from testgen.ui.views import test_results as view
from testgen.ui.views.test_results import CONTRACT_VERSION_MESSAGE, TestResultsPage

pytestmark = pytest.mark.unit


def _render(suite_type: SuiteType, summary: TestRunSummary | None = None, calls: dict | None = None) -> dict:
    """Render the page with its collaborators stubbed and return the widget's keyword arguments."""
    page = TestResultsPage.__new__(TestResultsPage)
    page.router = MagicMock()
    run = MagicMock(id="r1", test_suite_id="s1", project_code="DEFAULT")
    suite = MagicMock(suite_type=suite_type)
    with (
        patch.object(view, "st") as st_mock,
        patch.object(view, "session"),
        patch.object(view, "testgen") as testgen_mock,
        patch.object(view, "with_database_session", lambda func: func),
        patch.object(view, "date_service"),
        patch.object(view, "get_test_run_minimal", return_value=run),
        patch.object(view, "get_test_suite", return_value=suite),
        patch.object(view, "get_test_suite_minimal"),
        patch.object(view, "get_test_disposition", return_value=pd.DataFrame({"id": [], "action": []})),
        patch.object(view, "get_test_result_summary", return_value=[]),
        patch.object(view, "dataframe_to_json_records", return_value=[]),
        patch.object(view, "friendly_score", return_value="--"),
        patch.object(view.test_result_queries, "get_test_results", return_value=pd.DataFrame({"test_result_id": [], "action": []})),
        patch.object(view.test_result_queries, "get_test_results_count", return_value=0),
        patch.object(view.test_result_queries, "get_filter_options", return_value={}),
        patch.object(
            view, "get_test_run_summaries", return_value=([summary], 1) if summary else ([], 0)
        ) as get_summaries,
    ):
        st_mock.session_state = {}
        st_mock.query_params = {}
        page.render(run_id="r1")
    if calls is not None:
        calls["get_test_run_summaries"] = get_summaries.call_args
    return testgen_mock.test_results_widget.call_args.kwargs


def test_the_results_page_tells_the_widget_a_contract_run_is_a_contract():
    assert _render(SuiteType.CONTRACT)["data"]["run_info"]["is_contract"] is True


def test_the_results_page_tells_the_widget_a_regular_run_is_not_a_contract():
    assert _render(SuiteType.REGULAR)["data"]["run_info"]["is_contract"] is False


@pytest.mark.parametrize("error", [FrozenVersionError("v"), RemovedInDraftError("v", []), UnmatchedInDraftError("v", "d", [])])
def test_flagging_turns_a_refused_version_write_into_a_toast(error):
    handlers = _render(SuiteType.CONTRACT)
    with (
        patch.object(view, "st") as st_mock,
        patch.object(view.TestDefinition, "set_status_attribute", side_effect=error),
    ):
        handlers["on_FlagChanged_change"]({"test_definition_ids": ["td"], "value": True})

    st_mock.toast.assert_called_once()
    assert st_mock.toast.call_args.args[0] == CONTRACT_VERSION_MESSAGE
    st_mock.cache_data.clear.assert_not_called()


def test_saving_an_edit_turns_a_refused_version_write_into_a_toast():
    handlers = _render(SuiteType.CONTRACT)
    with (
        patch.object(view, "st") as st_mock,
        patch.object(view, "get_table_group_minimal", return_value=None),
        patch.object(view, "save_from_dialog", side_effect=FrozenVersionError("v")),
    ):
        handlers["on_EditTestSaved_change"]({})

    st_mock.toast.assert_called_once()
    assert st_mock.toast.call_args.args[0] == CONTRACT_VERSION_MESSAGE


def test_flagging_a_regular_run_still_writes():
    handlers = _render(SuiteType.REGULAR)
    with (
        patch.object(view, "st") as st_mock,
        patch.object(view.TestDefinition, "set_status_attribute") as set_status,
    ):
        handlers["on_FlagChanged_change"]({"test_definition_ids": ["td"], "value": True})

    set_status.assert_called_once_with("flagged", ["td"], True)
    st_mock.toast.assert_not_called()


def test_the_refusal_message_has_no_contraction():
    assert CONTRACT_VERSION_MESSAGE == "This contract's tests cannot be changed from this run."


def _summary(**overrides) -> TestRunSummary:
    started = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    fields = {
        "job_execution_id": uuid4(), "test_run_id": uuid4(), "job_schedule_id": None,
        "status": JobStatus.COMPLETED, "created_at": started, "started_at": started,
        "completed_at": started, "active_seconds": 252.0, "error_message": None, "progress": [],
        "table_groups_name": "sales_tables", "test_suite": "orders_contract", "project_code": "DEFAULT",
        "project_name": "Demo", "test_ct": 142, "passed_ct": 142, "warning_ct": 0, "failed_ct": 0,
        "error_ct": 0, "log_ct": 0, "dismissed_ct": 0, "dq_score_testing": 98.4, "total_count": 1,
        "test_starttime": started.replace(tzinfo=None),
    }
    fields.update(overrides)
    return TestRunSummary(**fields)


def test_the_results_page_sends_a_contract_runs_version_block():
    summary = _summary(
        version_number=3, version_frozen_at=datetime(2026, 10, 1, tzinfo=UTC), active_version_number=3
    )
    assert _render(SuiteType.CONTRACT, summary)["data"]["contract_version"] == {
        "value": "v3 active · Verification",
        "tooltip": "v3 is the agreement in force.",
    }


def test_the_results_page_sends_no_version_block_for_a_regular_run():
    assert _render(SuiteType.REGULAR, _summary(test_suite="nightly_checks"))["data"]["contract_version"] is None


def test_the_results_page_reads_the_runs_summary_by_its_id():
    calls: dict = {}
    _render(SuiteType.CONTRACT, _summary(), calls)
    assert calls["get_test_run_summaries"].kwargs["test_run_ids"] == ("r1",)
