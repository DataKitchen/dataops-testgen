"""The Test Runs list and the results page show standard suites and contracts, never monitor suites."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.enums import TEST_SUITE_TYPES, JobStatus, SuiteType
from testgen.common.models.test_run import RunVersionScope, TestRunSummary
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
    assert set(TEST_SUITE_TYPES) == {SuiteType.STANDARD, SuiteType.CONTRACT}


def test_the_runs_list_reads_regular_and_contract_runs():
    with patch.object(query_cache.TestRun, "select_summary", return_value=([], 0)) as select_summary:
        query_cache.get_test_run_summaries("DEFAULT")

    assert set(select_summary.call_args.kwargs["suite_types"]) == {SuiteType.STANDARD, SuiteType.CONTRACT}
    assert SuiteType.MONITOR not in select_summary.call_args.kwargs["suite_types"]


def test_the_version_scope_reads_regular_and_contract_runs():
    with patch.object(query_cache.TestRun, "select_version_scope", return_value=RunVersionScope(False, 0)) as scope:
        query_cache.get_test_run_version_scope("DEFAULT", None, None)

    assert set(scope.call_args.kwargs["suite_types"]) == {SuiteType.STANDARD, SuiteType.CONTRACT}


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
    assert "'standard'" in text
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
    assert text == "test_suites.suite_type IN ('standard', 'contract')"
    assert "'monitor'" not in text


@pytest.mark.parametrize(
    ("suite_type", "message"),
    [
        (SuiteType.CONTRACT, "Test run started for contract 'orders'."),
        (SuiteType.STANDARD, "Test run started for test suite 'orders'."),
        (None, "Test run started for test suite 'orders'."),
    ],
)
def test_the_run_started_message_names_what_ran(suite_type, message):
    assert runs_view.run_started_message(suite_type, "orders") == message


NO_CONTRACT = RunVersionScope(False, 0)


@contextmanager
def _rendered(*, summaries=(), scope=NO_CONTRACT, test_suites=(), **render_kwargs) -> Iterator:
    page = TestRunsPage.__new__(TestRunsPage)
    with (
        patch.object(runs_view, "testgen") as testgen_mock,
        patch.object(runs_view, "st") as st_mock,
        patch.object(runs_view, "get_project_summary"),
        patch.object(
            runs_view, "get_test_run_summaries", return_value=(list(summaries), len(summaries))
        ) as get_summaries,
        patch.object(runs_view, "get_test_run_version_scope", return_value=scope) as get_scope,
        patch.object(runs_view, "select_table_groups_minimal_where", return_value=[]),
        patch.object(runs_view, "select_test_suites_minimal_where", return_value=list(test_suites)),
        patch.object(runs_view, "TestRunScheduleDialog"),
        patch.object(runs_view, "TestRunNotificationSettingsDialog"),
        patch.object(runs_view, "session") as ui_session,
        patch.object(runs_view, "database_session"),
        patch.object(runs_view, "launch_run"),
        patch.object(runs_view, "run_list_args") as list_args,
        patch.object(runs_view, "Router") as router,
    ):
        st_mock.query_params = {}
        st_mock.session_state = {}
        ui_session.current_page = "test-runs"
        page.render(project_code="DEFAULT", **render_kwargs)
        yield SimpleNamespace(
            widget=testgen_mock.test_runs_widget.call_args.kwargs,
            get_summaries=get_summaries,
            get_scope=get_scope,
            run_list_args=list_args,
            set_query_params=router.return_value.set_query_params,
        )


def _runs_list_items(summary: TestRunSummary) -> list[dict]:
    with _rendered(summaries=[summary]) as rendered:
        return rendered.widget["data"]["test_runs"]


def _summary(**overrides) -> TestRunSummary:
    started = datetime(2026, 10, 11, 16, 20, tzinfo=UTC)
    fields = {
        "job_execution_id": uuid4(), "test_run_id": uuid4(), "job_schedule_id": None,
        "status": JobStatus.COMPLETED, "created_at": started, "started_at": started,
        "completed_at": started, "active_seconds": 280.0, "error_message": None, "progress": [],
        "table_groups_name": "sales_tables", "test_suite": "orders_contract", "project_code": "DEFAULT",
        "project_name": "Demo", "test_ct": 147, "passed_ct": 147, "warning_ct": 0, "failed_ct": 0,
        "error_ct": 0, "log_ct": 0, "dismissed_ct": 0, "dq_score_testing": None,
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


# -- Runs of every version ----------------------------------------------------

TABLE_GROUP_ID = uuid4()
CONTRACT = SimpleNamespace(
    id=uuid4(), test_suite="orders_contract", suite_type=SuiteType.CONTRACT, table_groups_id=TABLE_GROUP_ID
)
STANDARD = SimpleNamespace(
    id=uuid4(), test_suite="nightly_checks", suite_type=SuiteType.STANDARD, table_groups_id=TABLE_GROUP_ID
)


@pytest.mark.parametrize(("all_versions", "expected"), [(None, False), ("true", True)])
def test_the_list_reads_runs_of_every_version_only_when_the_url_asks(all_versions, expected):
    with _rendered(all_versions=all_versions) as rendered:
        pass

    assert rendered.get_summaries.call_args.kwargs["all_versions"] is expected


def test_the_scope_is_read_for_the_selected_filters_when_they_hold_a_contract():
    with _rendered(
        test_suites=[CONTRACT, STANDARD], table_group_id=str(TABLE_GROUP_ID), test_suite_id=str(CONTRACT.id)
    ) as rendered:
        pass

    assert rendered.get_scope.call_args.args == ("DEFAULT", str(TABLE_GROUP_ID), str(CONTRACT.id))


@pytest.mark.parametrize(
    "filters",
    [{}, {"test_suite_id": str(STANDARD.id)}, {"table_group_id": str(uuid4())}],
    ids=["no-contract-in-the-project", "a-standard-suite-selected", "another-table-group-selected"],
)
def test_the_scope_is_not_read_when_the_filters_hold_no_contract(filters):
    suites = [STANDARD] if not filters else [CONTRACT, STANDARD]
    with _rendered(test_suites=suites, scope=RunVersionScope(True, 5), **filters) as rendered:
        pass

    rendered.get_scope.assert_not_called()
    assert rendered.widget["data"]["version_toggle"]["visible"] is False


@pytest.mark.parametrize(
    ("scope", "all_versions", "toggle"),
    [
        (RunVersionScope(True, 3), None, {"visible": True, "checked": False, "hidden_count": 3}),
        (RunVersionScope(True, 0), "true", {"visible": True, "checked": True, "hidden_count": 0}),
        (RunVersionScope(False, 0), None, {"visible": False, "checked": False, "hidden_count": 0}),
    ],
)
def test_the_widget_gets_the_version_toggle(scope, all_versions, toggle):
    with _rendered(test_suites=[CONTRACT], scope=scope, all_versions=all_versions) as rendered:
        pass

    assert rendered.widget["data"]["version_toggle"] == toggle


@pytest.mark.parametrize(
    ("version_id", "list_args"),
    [(None, {}), ("draft-id", {"all_versions": "true"})],
    ids=["listed-by-default", "hidden-by-default"],
)
def test_starting_a_run_lists_it_where_it_shows(version_id, list_args):
    with _rendered(test_suites=[CONTRACT, STANDARD]) as rendered:
        rendered.run_list_args.return_value = list_args
        rendered.widget["on_RunTestsConfirmed_change"]({
            "test_suite_id": str(CONTRACT.id),
            "test_suite_name": CONTRACT.test_suite,
            **({"version_id": version_id} if version_id else {}),
        })

    rendered.run_list_args.assert_called_once_with(str(CONTRACT.id), version_id)
    assert rendered.set_query_params.call_args.args[0] == {"page": 1, **list_args}
