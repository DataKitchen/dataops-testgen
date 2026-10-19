"""The Test Runs list and the results page show regular suites and contracts, never monitor suites."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.enums import TEST_SUITE_TYPES, SuiteType
from testgen.ui.services import query_cache
from testgen.ui.views import test_runs as runs_view
from testgen.ui.views.test_results import TestResultsPage
from testgen.ui.views.test_runs import (
    TestRunNotificationSettingsDialog,
    TestRunScheduleDialog,
    TestRunsPage,
)

pytestmark = pytest.mark.unit


class _Stop(Exception):
    pass


def _text(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _suite_filter(call) -> str:
    return " ".join(_text(arg) for arg in call.args)


def test_the_shared_tuple_holds_regular_and_contract_only():
    assert set(TEST_SUITE_TYPES) == {SuiteType.REGULAR, SuiteType.CONTRACT}


def test_the_runs_list_reads_regular_and_contract_runs():
    with patch.object(query_cache.TestRun, "select_summary", return_value=([], 0)) as select_summary:
        query_cache.get_test_run_summaries("DEFAULT")

    assert set(select_summary.call_args.kwargs["suite_types"]) == {SuiteType.REGULAR, SuiteType.CONTRACT}
    assert SuiteType.MONITOR not in select_summary.call_args.kwargs["suite_types"]


def test_the_runs_page_suite_filter_lists_contracts_and_excludes_monitors():
    page = TestRunsPage.__new__(TestRunsPage)
    with (
        patch.object(runs_view, "testgen"),
        patch.object(runs_view, "st") as st_mock,
        patch.object(runs_view, "get_project_summary"),
        patch.object(runs_view, "get_test_run_summaries", return_value=([], 0)),
        patch.object(runs_view, "select_table_groups_minimal_where", return_value=[]),
        patch.object(runs_view, "select_test_suites_minimal_where", side_effect=_Stop) as select_suites,
    ):
        st_mock.query_params = {}
        with pytest.raises(_Stop):
            page.render(project_code="DEFAULT")

    text = _suite_filter(select_suites.call_args)
    assert "'regular'" in text
    assert "'contract'" in text
    assert "'monitor'" not in text


def test_the_notification_scope_options_list_contracts_and_exclude_monitors():
    dialog = TestRunNotificationSettingsDialog.__new__(TestRunNotificationSettingsDialog)
    dialog.ns_attrs = {"project_code": "DEFAULT"}
    with patch.object(runs_view, "select_test_suites_minimal_where", return_value=[]) as select_suites:
        dialog._get_component_props()

    text = _suite_filter(select_suites.call_args)
    assert "'contract'" in text
    assert "'monitor'" not in text


def test_the_schedule_dialog_lists_contracts_and_excludes_monitors():
    dialog = TestRunScheduleDialog.__new__(TestRunScheduleDialog)
    dialog.project_code = "DEFAULT"
    with patch.object(runs_view, "select_test_suites_minimal_where", return_value=[]) as select_suites:
        dialog.init()

    text = _suite_filter(select_suites.call_args)
    assert "'contract'" in text
    assert "'monitor'" not in text


def test_the_results_page_resolves_a_contract_run_and_not_a_monitor_run():
    page = TestResultsPage.__new__(TestResultsPage)
    page.router = MagicMock()
    run = MagicMock(test_suite_id="a-suite-id")
    with (
        patch("testgen.ui.views.test_results.get_test_run_minimal", return_value=run),
        patch("testgen.ui.views.test_results.get_test_suite", return_value=None) as get_suite,
    ):
        page.render(run_id="a-run-id")

    text = _text(get_suite.call_args.args[1])
    assert text == "test_suites.suite_type IN ('regular', 'contract')"
    assert "'monitor'" not in text


@pytest.mark.parametrize(
    ("suite_type", "message"),
    [
        (SuiteType.CONTRACT, "Test run started for contract 'orders'."),
        (SuiteType.REGULAR, "Test run started for test suite 'orders'."),
        (None, "Test run started for test suite 'orders'."),
    ],
)
def test_the_run_started_message_names_what_ran(suite_type, message):
    assert runs_view.run_started_message(suite_type, "orders") == message
