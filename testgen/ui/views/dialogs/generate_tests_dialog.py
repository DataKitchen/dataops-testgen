import time

import pandas as pd
import streamlit as st

import testgen.ui.services.test_suite_service as test_suite_service
from testgen.commands.run_generate_tests import run_test_gen_queries
from testgen.ui.components import widgets as testgen

ALL_TYPES_LABEL = "All Test Types"


@st.dialog(title="Generate Tests")
def generate_tests_dialog(test_suite: pd.Series) -> None:
    test_suite_id = test_suite["id"]
    test_suite_name = test_suite["test_suite"]
    table_group_id = test_suite["table_groups_id"]

    selected_set = ""
    generation_sets = test_suite_service.get_generation_set_choices()

    if generation_sets:
        generation_sets.insert(0, ALL_TYPES_LABEL)

        with st.container():
            selected_set = st.selectbox("Generation Set", generation_sets)
            if selected_set == ALL_TYPES_LABEL:
                selected_set = ""

    test_ct, unlocked_test_ct, unlocked_edits_ct = test_suite_service.get_test_suite_refresh_warning(test_suite_id)
    if test_ct:
        unlocked_message = ""
        if unlocked_edits_ct > 0:
            unlocked_message = "Manual changes have been made to auto-generated tests in this test suite that have not been locked. "
        elif unlocked_test_ct > 0:
            unlocked_message = "Auto-generated tests are present in this test suite that have not been locked. "

        warning_message = f"""
            {unlocked_message}
            Generating tests now will overwrite unlocked tests subject to auto-generation based on the latest profiling.
            \n\n_Auto-generated Tests: {test_ct}, Unlocked: {unlocked_test_ct}, Edited Unlocked: {unlocked_edits_ct}_
            """

        with st.container():
            st.warning(warning_message, icon=":material/warning:")
            if unlocked_edits_ct > 0:
                if st.button("Lock Edited Tests"):
                    if test_suite_service.lock_edited_tests(test_suite_id):
                        st.info("Edited tests have been successfully locked.")

    with st.container():
        st.markdown(f"Execute test generation for the test suite **{test_suite_name}**?")

    if testgen.expander_toggle(expand_label="Show CLI command", key="test_suite:keys:generate-tests-show-cli"):
        st.code(
            f"testgen run-test-generation --table-group-id {table_group_id} --test-suite-key {test_suite_name}",
            language="shellSession",
        )

    button_container = st.empty()
    status_container = st.empty()

    test_generation_button = None
    with button_container:
        _, button_column = st.columns([.75, .25])
        with button_column:
            test_generation_button = st.button("Generate Tests", use_container_width=True)

    if test_generation_button:
        button_container.empty()
        status_container.info("Starting test generation ...")

        try:
            run_test_gen_queries(table_group_id, test_suite_name, selected_set)
        except Exception as e:
            status_container.error(f"Test generation encountered errors: {e!s}.")

        status_container.success(f"Test generation completed for test suite **{test_suite_name}**.")
        time.sleep(1)
        st.cache_data.clear()
        st.rerun()
