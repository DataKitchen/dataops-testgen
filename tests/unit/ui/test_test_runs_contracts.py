"""The Test Runs list and the results page show regular suites and contracts, never monitor suites."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.enums import TEST_SUITE_TYPES, JobStatus, SuiteType
from testgen.common.models.test_run import TestRunSummary
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


def _runs_list_items(summary: TestRunSummary) -> list[dict]:
    page = TestRunsPage.__new__(TestRunsPage)
    with (
        patch.object(runs_view, "testgen") as testgen_mock,
        patch.object(runs_view, "st") as st_mock,
        patch.object(runs_view, "get_project_summary"),
        patch.object(runs_view, "get_test_run_summaries", return_value=([summary], 1)),
        patch.object(runs_view, "select_table_groups_minimal_where", return_value=[]),
        patch.object(runs_view, "select_test_suites_minimal_where", return_value=[]),
        patch.object(runs_view, "TestRunScheduleDialog"),
        patch.object(runs_view, "TestRunNotificationSettingsDialog"),
        patch.object(runs_view, "session"),
    ):
        st_mock.query_params = {}
        st_mock.session_state = {}
        page.render(project_code="DEFAULT")
    return testgen_mock.test_runs_widget.call_args.kwargs["data"]["test_runs"]


def _summary(**overrides) -> TestRunSummary:
    started = datetime(2026, 10, 11, 16, 20, tzinfo=UTC)
    fields = {
        "job_execution_id": uuid4(), "test_run_id": uuid4(), "job_schedule_id": None,
        "status": JobStatus.COMPLETED, "created_at": started, "started_at": started,
        "completed_at": started, "active_seconds": 280.0, "error_message": None, "progress": [],
        "table_groups_name": "sales_tables", "test_suite": "orders_contract", "project_code": "DEFAULT",
        "project_name": "Demo", "test_ct": 147, "passed_ct": 147, "warning_ct": 0, "failed_ct": 0,
        "error_ct": 0, "log_ct": 0, "dismissed_ct": 0, "dq_score_testing": None, "total_count": 1,
        "test_starttime": started.replace(tzinfo=None),
    }
    fields.update(overrides)
    return TestRunSummary(**fields)


def test_the_runs_list_sends_a_contract_runs_version_caption():
    items = _runs_list_items(_summary(version_number=4, active_version_number=3))
    assert items[0]["version_caption"] == "v4 draft · Preview"


def test_the_runs_list_sends_no_caption_for_a_regular_run():
    items = _runs_list_items(_summary(test_suite="nightly_checks"))
    assert items[0]["version_caption"] is None
