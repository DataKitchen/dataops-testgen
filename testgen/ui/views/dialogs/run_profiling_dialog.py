import time

import streamlit as st

from testgen.commands.run_profiling_bridge import run_profiling_in_background
from testgen.common.models import with_database_session
from testgen.common.models.table_group import TableGroup, TableGroupMinimal
from testgen.ui.components import widgets as testgen
from testgen.ui.session import session
from testgen.utils import to_dataframe

LINK_KEY = "run_profiling_dialog:keys:go-to-runs"
LINK_HREF = "profiling-runs"


@st.dialog(title="Run Profiling")
@with_database_session
def run_profiling_dialog(project_code: str, table_group: TableGroupMinimal | None = None, default_table_group_id: str | None = None) -> None:
    if table_group:
        table_group_id: str = str(table_group.id)
        table_group_name: str = table_group.table_groups_name
    else:
        table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)
        table_groups_df = to_dataframe(table_groups, TableGroupMinimal.columns())
        table_group_id: str = testgen.select(
            label="Table Group",
            options=table_groups_df,
            value_column="id",
            display_column="table_groups_name",
            default_value=default_table_group_id,
            required=True,
            placeholder="Select table group to profile",
        )
        if table_group_id:
            table_group_name: str = table_groups_df.loc[table_groups_df["id"] == table_group_id, "table_groups_name"].iloc[0]
        testgen.whitespace(1)

    if table_group_id:        
        with st.container():
            st.markdown(f"Execute profiling for the table group **{table_group_name}**?")
            st.markdown(":material/info: _Profiling will be performed in a background process._")

        if testgen.expander_toggle(expand_label="Show CLI command", key="test_suite:keys:run-tests-show-cli"):
            st.code(f"testgen run-profile --table-group-id {table_group_id}", language="shellSession")

    button_container = st.empty()
    status_container = st.empty()

    with button_container:
        _, button_column = st.columns([.85, .15])
        with button_column:
            profile_button = st.button("Run Profiling", use_container_width=True, disabled=not table_group_id)

    if profile_button:
        button_container.empty()
        status_container.info("Starting profiling run ...")

        try:
            run_profiling_in_background(table_group_id)
        except Exception as e:
            status_container.error(f"Profiling run encountered errors: {e!s}.")

    # The second condition is needed for the link to work
    if profile_button or st.session_state.get(LINK_KEY):
        with status_container.container():
            st.success(
                f"Profiling run started for table group **{table_group_name}**."
            )

            if session.current_page != LINK_HREF:
                testgen.link(
                    label="Go to Profiling Runs",
                    href=LINK_HREF,
                    params={ "project_code": project_code, "table_group": table_group_id },
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
