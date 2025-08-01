import logging
import typing
from functools import partial

import pandas as pd
import streamlit as st

import testgen.common.process_service as process_service
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
from testgen.common.models import with_database_session
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries import project_queries, test_run_queries
from testgen.ui.services import user_session_service
from testgen.ui.session import session, temp_value
from testgen.ui.views.dialogs.manage_schedules import ScheduleDialog
from testgen.ui.views.dialogs.run_tests_dialog import run_tests_dialog
from testgen.utils import friendly_score, to_int

PAGE_SIZE = 50
PAGE_ICON = "labs"
PAGE_TITLE = "Test Runs"
LOG = logging.getLogger("testgen")


class TestRunsPage(Page):
    path = "test-runs"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Quality Testing",
        order=0,
        roles=[ role for role in typing.get_args(user_session_service.RoleType) if role != "catalog" ],
    )

    def render(self, project_code: str, table_group_id: str | None = None, test_suite_id: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "test-results",
        )

        user_can_run = user_session_service.user_can_edit()
        if render_empty_state(project_code, user_can_run):
            return

        group_filter_column, suite_filter_column, actions_column = st.columns([.3, .3, .4], vertical_alignment="bottom")

        with group_filter_column:
            table_groups_df = get_db_table_group_choices(project_code)
            table_group_id = testgen.select(
                options=table_groups_df,
                value_column="id",
                display_column="table_groups_name",
                default_value=table_group_id,
                bind_to_query="table_group_id",
                label="Table Group",
                placeholder="---",
            )

        with suite_filter_column:
            test_suites_df = get_db_test_suite_choices(project_code, table_group_id)
            test_suite_id = testgen.select(
                options=test_suites_df,
                value_column="id",
                display_column="test_suite",
                default_value=test_suite_id,
                bind_to_query="test_suite_id",
                label="Test Suite",
                placeholder="---",
            )

        with actions_column:
            testgen.flex_row_end(actions_column)

            st.button(
                ":material/today: Test Run Schedules",
                help="Manage when test suites should run",
                on_click=partial(TestRunScheduleDialog().open, project_code)
            )

            if user_can_run:
                st.button(
                    ":material/play_arrow: Run Tests",
                    help="Run tests for a test suite",
                    on_click=partial(run_tests_dialog, project_code, None, test_suite_id)
                )

        fm.render_refresh_button(actions_column)

        testgen.whitespace(0.5)
        list_container = st.container()

        test_runs_df = get_db_test_runs(project_code, table_group_id, test_suite_id)
        page_index = testgen.paginator(count=len(test_runs_df), page_size=PAGE_SIZE)
        test_runs_df["dq_score_testing"] = test_runs_df["dq_score_testing"].map(lambda score: friendly_score(score))
        paginated_df = test_runs_df[PAGE_SIZE * page_index : PAGE_SIZE * (page_index + 1)]

        with list_container:
            testgen_component(
                "test_runs",
                props={
                    "items": paginated_df.to_json(orient="records"),
                    "permissions": {
                        "can_run": user_can_run,
                        "can_edit": user_can_run,
                    },
                },
                event_handlers={
                    "RunCanceled": on_cancel_run,
                    "RunsDeleted": partial(on_delete_runs, project_code, table_group_id, test_suite_id),
                }
            )


class TestRunScheduleDialog(ScheduleDialog):

    title = "Test Run Schedules"
    arg_label = "Test Suite"
    job_key = "run-tests"
    test_suites: pd.DataFrame | None = None

    def init(self) -> None:
        self.test_suites = get_db_test_suite_choices(self.project_code)

    def get_arg_value(self, job):
        return job.kwargs["test_suite_key"]

    def arg_value_input(self) -> tuple[bool, list[typing.Any], dict[str, typing.Any]]:
        ts_name = testgen.select(
            label="Test Suite",
            options=self.test_suites,
            value_column="test_suite",
            display_column="test_suite",
            required=True,
            placeholder="Select test suite",
        )
        return bool(ts_name), [], {"project_key": self.project_code, "test_suite_key": ts_name}


def render_empty_state(project_code: str, user_can_run: bool) -> bool:
    project_summary_df = project_queries.get_summary_by_code(project_code)
    if project_summary_df["test_runs_ct"]:
        return False

    label="No test runs yet"
    testgen.whitespace(5)
    if not project_summary_df["connections_ct"]:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.Connection,
            action_label="Go to Connections",
            link_href="connections",
            link_params={ "project_code": project_code },
        )
    elif not project_summary_df["table_groups_ct"]:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.TableGroup,
            action_label="Go to Table Groups",
            link_href="table-groups",
            link_params={
                "project_code": project_code,
                "connection_id": str(project_summary_df["default_connection_id"]),
            }
        )
    elif not project_summary_df["test_suites_ct"] or not project_summary_df["test_definitions_ct"]:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.TestSuite,
            action_label="Go to Test Suites",
            link_href="test-suites",
            link_params={ "project_code": project_code },
        )
    else:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.TestExecution,
            action_label="Run Tests",
            action_disabled=not user_can_run,
            button_onclick=partial(run_tests_dialog, project_code),
            button_icon="play_arrow",
        )
    return True


def on_cancel_run(test_run: pd.Series) -> None:
    process_status, process_message = process_service.kill_test_run(to_int(test_run["process_id"]))
    if process_status:
        test_run_queries.update_status(test_run["test_run_id"], "Cancelled")
    fm.reset_post_updates(str_message=f":{'green' if process_status else 'red'}[{process_message}]", as_toast=True)


@st.dialog(title="Delete Test Runs")
@with_database_session
def on_delete_runs(project_code: str, table_group_id: str, test_suite_id: str, test_run_ids: list[str]) -> None:
    def on_delete_confirmed(*_args) -> None:
        set_delete_confirmed(True)

    message = f"Are you sure you want to delete the {len(test_run_ids)} selected test runs?"
    constraint = {
        "warning": "Any running processes will be canceled.",
        "confirmation": "Yes, cancel and delete the test runs.",
    }
    if len(test_run_ids) == 1 and (test_run_id := test_run_ids[0]):
        message = "Are you sure you want to delete the selected test run?"
        constraint["confirmation"] = "Yes, cancel and delete the test run."

    if not test_run_queries.is_running(test_run_ids):
        constraint = None

    result = None
    delete_confirmed, set_delete_confirmed = temp_value("test-runs:confirm-delete", default=False)
    testgen.testgen_component(
        "confirm_dialog",
        props={
            "project_code": project_code,
            "message": message,
            "constraint": constraint,
            "button_label": "Delete",
            "button_color": "warn",
            "result": result,
        },
        on_change_handlers={
            "ActionConfirmed": on_delete_confirmed,
        },
    )

    if delete_confirmed():
        try:
            with st.spinner("Deleting runs ..."):
                test_runs = _get_db_test_runs(project_code, table_group_id, test_suite_id, test_runs_ids=test_run_ids)
                for _, test_run in test_runs.iterrows():
                    test_run_id = test_run["test_run_id"]
                    if test_run["status"] == "Running":
                        process_status, _ = process_service.kill_test_run(to_int(test_run["process_id"]))
                        if process_status:
                            test_run_queries.update_status(test_run_id, "Cancelled")
                test_run_queries.cascade_delete_multiple_test_runs(test_run_ids)
            st.rerun()
        except Exception:
            LOG.exception("Failed to delete test run")
            result = {"success": False, "message": "Unable to delete the test run, try again."}


@st.cache_data(show_spinner=False)
def run_test_suite_lookup_query(schema: str, project_code: str, table_groups_id: str | None = None) -> pd.DataFrame:
    table_group_condition = f" AND test_suites.table_groups_id = '{table_groups_id}' " if table_groups_id else ""
    sql = f"""
    SELECT test_suites.id::VARCHAR(50),
        test_suites.test_suite
    FROM {schema}.test_suites
        LEFT JOIN {schema}.table_groups ON test_suites.table_groups_id = table_groups.id
    WHERE test_suites.project_code = '{project_code}'
    {table_group_condition}
    ORDER BY test_suites.test_suite
    """
    return db.retrieve_data(sql)


@st.cache_data(show_spinner=False)
def get_db_table_group_choices(project_code: str) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(schema, project_code)


@st.cache_data(show_spinner=False)
def get_db_test_suite_choices(project_code: str, table_groups_id: str | None = None) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    return run_test_suite_lookup_query(schema, project_code, table_groups_id)


@st.cache_data(show_spinner="Loading data ...")
def get_db_test_runs(
    project_code: str,
    table_groups_id: str | None = None,
    test_suite_id: str | None = None,
    test_runs_ids: list[str] | None = None,
) -> pd.DataFrame:
    return _get_db_test_runs(
        project_code, table_groups_id=table_groups_id, test_suite_id=test_suite_id, test_runs_ids=test_runs_ids
    )


def _get_db_test_runs(
    project_code: str,
    table_groups_id: str | None = None,
    test_suite_id: str | None = None,
    test_runs_ids: list[str] | None = None,
) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    table_group_condition = f" AND test_suites.table_groups_id = '{table_groups_id}' " if table_groups_id else ""
    test_suite_condition = f" AND test_suites.id = '{test_suite_id}' " if test_suite_id else ""

    test_runs_conditions = ""
    if test_runs_ids and len(test_runs_ids) > 0:
        test_runs_ids_ = [f"'{run_id}'" for run_id in test_runs_ids]
        test_runs_conditions = f" AND test_runs.id::VARCHAR IN ({', '.join(test_runs_ids_)})"

    sql = f"""
    WITH run_results AS (
        SELECT test_run_id,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Passed' THEN 1
                    ELSE 0
                END
            ) as passed_ct,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Warning' THEN 1
                    ELSE 0
                END
            ) as warning_ct,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Failed' THEN 1
                    ELSE 0
                END
            ) as failed_ct,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                    AND result_status = 'Error' THEN 1
                    ELSE 0
                END
            ) as error_ct,
            SUM(
                CASE
                    WHEN COALESCE(disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                    ELSE 0
                END
            ) as dismissed_ct
        FROM {schema}.test_results
        GROUP BY test_run_id
    )
    SELECT test_runs.id::VARCHAR as test_run_id,
        test_runs.test_starttime,
        table_groups.table_groups_name,
        test_suites.test_suite,
        test_runs.status,
        test_runs.duration,
        test_runs.process_id,
        test_runs.log_message,
        test_runs.test_ct,
        run_results.passed_ct,
        run_results.warning_ct,
        run_results.failed_ct,
        run_results.error_ct,
        run_results.dismissed_ct,
        test_runs.dq_score_test_run AS dq_score_testing
    FROM {schema}.test_runs
        LEFT JOIN run_results ON (test_runs.id = run_results.test_run_id)
        INNER JOIN {schema}.test_suites ON (test_runs.test_suite_id = test_suites.id)
        INNER JOIN {schema}.table_groups ON (test_suites.table_groups_id = table_groups.id)
        INNER JOIN {schema}.projects ON (test_suites.project_code = projects.project_code)
    WHERE test_suites.project_code = '{project_code}'
    {table_group_condition}
    {test_suite_condition}
    {test_runs_conditions}
    ORDER BY test_runs.test_starttime DESC;
    """

    return db.retrieve_data(sql)
