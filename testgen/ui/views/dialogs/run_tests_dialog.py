import time

import streamlit as st

from testgen.commands.run_execute_tests import run_execution_steps_in_background
from testgen.common.models import with_database_session
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.session import session
from testgen.utils import to_dataframe

LINK_KEY = "run_tests_dialog:keys:go-to-runs"
LINK_HREF = "test-runs"


@st.dialog(title="Run Tests")
@with_database_session
def run_tests_dialog(project_code: str, test_suite: TestSuiteMinimal | None = None, default_test_suite_id: str | None = None) -> None:
    if test_suite:
        test_suite_id: str = str(test_suite.id)
        test_suite_name: str = test_suite.test_suite
    else:
        test_suites = TestSuite.select_minimal_where(TestSuite.project_code == project_code)
        test_suites_df = to_dataframe(test_suites, TestSuiteMinimal.columns())
        test_suite_id: str = testgen.select(
            label="Test Suite",
            options=test_suites_df,
            value_column="id",
            display_column="test_suite",
            default_value=default_test_suite_id,
            required=True,
            placeholder="Select test suite to run",
        )
        if test_suite_id:
            test_suite_name: str = next(item.test_suite for item in test_suites if item.id == test_suite_id)
        testgen.whitespace(1)

    if test_suite_id:
        with st.container():
            st.markdown(f"Run tests for the test suite **{test_suite_name}**?")
            st.markdown(":material/info: _Test execution will be performed in a background process._")

        if testgen.expander_toggle(expand_label="Show CLI command", key="run_tests_dialog:keys:show-cli"):
            st.code(
                f"testgen run-tests --project-key {project_code} --test-suite-key {test_suite_name}",
                language="shellSession"
            )

    button_container = st.empty()
    status_container = st.empty()

    run_test_button = None
    with button_container:
        _, button_column = st.columns([.8, .2])
        with button_column:
            run_test_button = st.button("Run Tests", use_container_width=True, disabled=not test_suite_id)

    if run_test_button:
        button_container.empty()
        status_container.info("Starting test run ...")

        try:
            run_execution_steps_in_background(project_code, test_suite_name)
        except Exception as e:
            status_container.error(f"Test run encountered errors: {e!s}.")

    # The second condition is needed for the link to work
    if run_test_button or st.session_state.get(LINK_KEY):
        with status_container.container():
            st.success(
                f"Test run started for test suite **{test_suite_name}**."
            )

            if session.current_page != LINK_HREF:
                testgen.link(
                    label="Go to Test Runs",
                    href=LINK_HREF,
                    params={ "project_code": project_code, "test_suite": test_suite_id },
                    right_icon="chevron_right",
                    underline=False,
                    height=40,
                    key=LINK_KEY,
                    style="margin-left: auto; border-radius: 4px; border: var(--button-stroked-border); padding: 8px 8px 8px 16px; color: var(--primary-color)",
                )
            else:
                time.sleep(2)
                st.cache_data.clear()
                st.rerun()
