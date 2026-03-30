import json

import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
from testgen.common.models import with_database_session
from testgen.common.pii_masking import get_pii_columns, mask_profiling_pii
from testgen.ui.components.widgets.testgen_component import testgen_component
from testgen.ui.session import session
from testgen.utils import make_json_safe


def view_profiling_button(column_name: str, table_name: str, table_groups_id: str):
    if column_name and column_name not in ("(multi-column)", "N/A") and table_name and table_name not in "(multi-table)":
        if st.button(
            ":material/insert_chart: Profiling",
            help="View profiling for highlighted column",
            use_container_width=True,
        ):
            profiling_results_dialog(column_name, table_name, table_groups_id)


@st.dialog(title="Column Profiling Results")
@with_database_session
def profiling_results_dialog(column_name: str, table_name: str, table_groups_id: str):
    column = profiling_queries.get_column_by_name(column_name, table_name, table_groups_id)

    if column:
        if not session.auth.user_has_permission("view_pii"):
            pii_columns = get_pii_columns(table_groups_id, table_name=table_name)
            mask_profiling_pii(column, pii_columns)

        testgen_component(
            "column_profiling_results",
            props={ "column": json.dumps(make_json_safe(column)) },
        )
