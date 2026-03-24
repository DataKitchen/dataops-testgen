import streamlit as st

from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.test_suite import TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.router import Router
from testgen.ui.session import session

LINK_HREF = "test-runs"
RESULT_KEY = "run_tests_dialog:result"


def run_tests_dialog_widget(
    project_code: str,
    dialog: dict,
    on_close: callable,
    test_suite_id: str | None = None,
) -> None:
    test_suites = TestSuite.select_minimal_where(
        TestSuite.project_code == project_code,
        TestSuite.is_monitor.isnot(True),
    )

    def on_run_tests_confirmed(data: dict) -> None:
        selected_id = data.get("test_suite_id")
        selected_name = data.get("test_suite_name")
        success = True
        message = f"Test run started for test suite '{selected_name}'."
        show_link = session.current_page != LINK_HREF
        try:
            with database_session():
                JobExecution.submit(
                    job_key="run-tests",
                    kwargs={"test_suite_id": str(selected_id)},
                    source="ui",
                    project_code=project_code,
                )
        except Exception as e:
            success = False
            message = f"Test run could not be started: {e!s}."
            show_link = False
        st.session_state[RESULT_KEY] = {"success": success, "message": message, "show_link": show_link}
        if success and not show_link:
            st.cache_data.clear()
            on_close()

    def on_go_to_test_runs(payload: dict) -> None:
        st.session_state.pop(RESULT_KEY, None)
        Router().navigate(to=LINK_HREF, with_args=payload)

    def on_close_clicked(*_) -> None:
        st.session_state.pop(RESULT_KEY, None)
        on_close()

    testgen.run_tests_dialog_widget(
        key="run_tests_dialog",
        data={
            "dialog": dialog,
            "project_code": project_code,
            "test_suites": [{"value": str(ts.id), "label": ts.test_suite} for ts in test_suites],
            "default_test_suite_id": str(test_suite_id) if test_suite_id else None,
            "result": st.session_state.get(RESULT_KEY),
        },
        on_RunTestsConfirmed_change=on_run_tests_confirmed,
        on_GoToTestRunsClicked_change=on_go_to_test_runs,
        on_CloseClicked_change=on_close_clicked,
    )
