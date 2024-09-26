import logging

import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.form_service as fm
from testgen.ui.views.profiling_details import show_profiling_detail

LOG = logging.getLogger("testgen")

BUTTON_TEXT = "Profiling　→"   # Profiling　⚲
BUTTON_HELP = "Review profiling for highlighted column"


def view_profiling_button(button_container, str_table_name, str_column_name,
                         str_profile_run_id=None, str_table_groups_id=None):
    with button_container:
        if st.button(
            BUTTON_TEXT, help=BUTTON_HELP, use_container_width=True
        ):
            profiling_results_dialog(str_table_name, str_column_name, str_profile_run_id, str_table_groups_id)


@st.dialog(title="Profiling Results")
def profiling_results_dialog(str_table_name, str_column_name, str_profile_run_id=None, str_table_groups_id=None):
    if not str_profile_run_id:
        if str_table_groups_id:
            str_profile_run_id = profiling_queries.get_latest_profile_run(str_table_groups_id)

    if str_profile_run_id:
        df = profiling_queries.get_profiling_detail(str_profile_run_id, str_table_name, str_column_name)
        if not df.empty:
            fm.show_prompt(f"Column: {str_column_name}, Table: {str_table_name}")
            show_profiling_detail(df.iloc[0], 300)
