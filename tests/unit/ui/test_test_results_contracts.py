"""On the results page, a contract run's Flag and Edit are disabled and refused writes become a toast."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from testgen.common.enums import SuiteType
from testgen.common.models.suite_version import FrozenVersionError, RemovedInDraftError, UnmatchedInDraftError
from testgen.ui.views import test_results as view
from testgen.ui.views.test_results import CONTRACT_VERSION_MESSAGE, TestResultsPage

pytestmark = pytest.mark.unit


def _render(suite_type: SuiteType) -> dict:
    """Render the page with its collaborators stubbed and return the widget's keyword arguments."""
    page = TestResultsPage.__new__(TestResultsPage)
    page.router = MagicMock()
    run = MagicMock(test_suite_id="s1", project_code="DEFAULT")
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
    ):
        st_mock.session_state = {}
        st_mock.query_params = {}
        page.render(run_id="r1")
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
        patch.object(view.TestDefinition, "save", side_effect=FrozenVersionError("v")),
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
