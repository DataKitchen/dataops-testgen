import streamlit as st
from sqlalchemy.sql.expression import func

from testgen.common.models import with_database_session
from testgen.common.models.profiling_run import ProfilingRun
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.queries.profiling_queries import COLUMN_PROFILING_FIELDS
from testgen.ui.services.database_service import fetch_one_from_db
from testgen.utils import make_json_safe


def column_history_dialog(*args) -> None:
    st.session_state["column_history_dialog:run_id"] = None
    _column_history_dialog(*args)
    

@st.dialog(title="Column History")
@with_database_session
def _column_history_dialog(
    table_group_id: str,
    schema_name: str,
    table_name: str,
    column_name: str,
    add_date: int,
) -> None:
    testgen.css_class("l-dialog")
    caption_column, loading_column = st.columns([ 0.8, 0.2 ], vertical_alignment="bottom")

    with caption_column:
        testgen.caption(f"Table > Column: <b>{table_name} > {column_name}</b>")

    with loading_column:
        with st.spinner("Loading data ..."):
            profiling_runs = ProfilingRun.select_minimal_where(
                ProfilingRun.table_groups_id == table_group_id,
                ProfilingRun.profiling_starttime >= func.to_timestamp(add_date),
            )
            profiling_runs = [run.to_dict(json_safe=True) for run in profiling_runs]
            run_id = st.session_state.get("column_history_dialog:run_id") or profiling_runs[0]["id"]
            selected_item = get_run_column(run_id, schema_name, table_name, column_name)

    testgen_component(
        "column_profiling_history",
        props={
            "profiling_runs": [
                {
                    "run_id": run["id"],
                    "run_date": run["profiling_starttime"],
                } for run in profiling_runs
            ],
            "selected_item": make_json_safe(selected_item),
        },
        on_change_handlers={
            "RunSelected": on_run_selected,
        }
    )


def on_run_selected(run_id: str) -> None:
    st.session_state["column_history_dialog:run_id"] = run_id


@st.cache_data(show_spinner=False)
def get_run_column(run_id: str, schema_name: str, table_name: str, column_name: str) -> dict:
    query = f"""
    SELECT
        profile_run_id::VARCHAR,
        general_type,
        {COLUMN_PROFILING_FIELDS}
    FROM profile_results
    WHERE profile_run_id = :run_id
        AND schema_name = :schema_name
        AND table_name = :table_name
        AND column_name = :column_name;
    """
    params = {
        "run_id": run_id,
        "schema_name": schema_name,
        "table_name": table_name,
        "column_name": column_name,
    }
    result = fetch_one_from_db(query, params)
    return dict(result) if result else None
