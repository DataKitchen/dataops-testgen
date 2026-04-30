from uuid import UUID

import streamlit as st

from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.router import Router
from testgen.ui.services.query_cache import get_profiling_run_summaries, get_table_group_stats
from testgen.ui.session import session

LINK_HREF = "profiling-runs"
RESULT_KEY = "run_profiling_dialog:result"


def run_profiling_dialog_widget(
    project_code: str,
    dialog: dict,
    on_close: callable,
    table_group_id: str | UUID | None = None,
    allow_selection: bool = False,
) -> None:
    if not table_group_id and not allow_selection:
        raise ValueError("Table Group ID must be specified when selection is not allowed")

    def on_run_profiling_confirmed(table_group: dict) -> None:
        success = True
        message = f"Profiling run started for table group '{table_group['table_groups_name']}'."
        show_link = session.current_page != LINK_HREF
        try:
            with database_session():
                JobExecution.submit(
                    job_key="run-profile",
                    kwargs={"table_group_id": str(table_group["id"])},
                    source="ui",
                    project_code=project_code,
                )
        except Exception as error:
            success = False
            message = f"Profiling run could not be started: {error!s}."
            show_link = False
        st.session_state[RESULT_KEY] = {"success": success, "message": message, "show_link": show_link}
        if success:
            get_profiling_run_summaries.clear()
            if not show_link:
                on_close()

    def on_go_to_profiling_runs_clicked(payload: dict) -> None:
        st.session_state.pop(RESULT_KEY, None)
        Router().navigate(to=LINK_HREF, with_args={"project_code": project_code, "table_group_id": payload})

    def on_close_clicked(*_) -> None:
        st.session_state.pop(RESULT_KEY, None)
        on_close()

    table_groups = get_table_group_stats(
        project_code=project_code,
        table_group_id=table_group_id if not allow_selection else None,
    )

    testgen.run_profiling_dialog_widget(
        key="run_profiling_dialog",
        data={
            "dialog": dialog,
            "table_groups": [tg.to_dict(json_safe=True) for tg in table_groups],
            "selected_id": str(table_group_id) if table_group_id else None,
            "allow_selection": allow_selection,
            "result": st.session_state.get(RESULT_KEY),
        },
        on_RunProfilingConfirmed_change=on_run_profiling_confirmed,
        on_GoToProfilingRunsClicked_change=on_go_to_profiling_runs_clicked,
        on_CloseClicked_change=on_close_clicked,
    )
