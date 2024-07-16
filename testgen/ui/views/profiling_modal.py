import logging

import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.form_service as fm
from testgen.ui.components import widgets as testgen
from testgen.ui.views.profiling_details import show_profiling_detail

LOG = logging.getLogger("testgen")

BUTTON_TEXT = ":green[Profiling　→]"   # Profiling　⚲
BUTTON_HELP = "Review profiling for highlighted column"
FORM_HEADER = "Profiling Results"


def view_profiling_modal(button_container, str_table_name, str_column_name,
                         str_profile_run_id=None, str_table_groups_id=None):
    str_prompt = f"Column: {str_column_name}, Table: {str_table_name}"

    modal_viewer = testgen.Modal(title=None, key="dk-view", max_width=1100)

    with button_container:
        if st.button(
            BUTTON_TEXT, help=BUTTON_HELP, use_container_width=True
        ):
            modal_viewer.open()

    if modal_viewer.is_open():
        with modal_viewer.container():
            if not str_profile_run_id:
                if str_table_groups_id:
                    str_profile_run_id = profiling_queries.get_latest_profile_run(str_table_groups_id)

            if str_profile_run_id:
                df = profiling_queries.get_profiling_detail(str_profile_run_id, str_table_name, str_column_name)
                if not df.empty:
                    fm.render_modal_header(str_title=FORM_HEADER, str_prompt=str_prompt)
                    show_profiling_detail(df.iloc[0], 300)

