import time
from uuid import UUID

import streamlit as st

from testgen.commands.run_profiling import run_profiling_in_background
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.table_group import TableGroup
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.router import Router
from testgen.ui.session import session, temp_value

LINK_HREF = "profiling-runs"


@st.dialog(title="Run Profiling")
def run_profiling_dialog(project_code: str, table_group_id: str | UUID | None = None, allow_selection: bool = False) -> None:
    if not table_group_id and not allow_selection:
        raise ValueError("Table Group ID must be specified when selection is not allowed")

    def on_go_to_profiling_runs_clicked(table_group_id: str) -> None:
        set_navigation_params({"project_code": project_code, "table_group_id": table_group_id})

    def on_run_profiling_confirmed(table_group: dict) -> None:
        set_table_group(table_group)
        set_run_profiling(True)

    get_navigation_params, set_navigation_params = temp_value("run_profiling_dialog:go_to_profiling_run", default=None)
    if params := get_navigation_params():
        Router().navigate(to=LINK_HREF, with_args=params)

    should_run_profiling, set_run_profiling = temp_value("run_profiling_dialog:run_profiling", default=False)
    get_table_group, set_table_group = temp_value("run_profiling_dialog:table_group", default=None)

    table_groups = TableGroup.select_stats(
        project_code=project_code,
        table_group_id=table_group_id if not allow_selection else None,
    )

    result = None
    if should_run_profiling():
        selected_table_group = get_table_group()
        success = True
        message = f"Profiling run started for table group '{selected_table_group['table_groups_name']}'."
        show_link = session.current_page != LINK_HREF

        try:
            run_profiling_in_background(selected_table_group["id"])
        except Exception as error:
            success = False
            message = f"Profiling run could not be started: {error!s}."
            show_link = False
        result = {"success": success, "message": message, "show_link": show_link}

    testgen.testgen_component(
        "run_profiling_dialog",
        props={
            "table_groups": [table_group.to_dict(json_safe=True) for table_group in table_groups],
            "selected_id": str(table_group_id),
            "allow_selection": allow_selection,
            "result": result,
        },
        on_change_handlers={
            "GoToProfilingRunsClicked": on_go_to_profiling_runs_clicked,
            "RunProfilingConfirmed": on_run_profiling_confirmed,
        },
    )

    if result and result["success"] and not result["show_link"]:
        time.sleep(2)
        ProfilingRun.select_summary.clear()
        st.rerun()
