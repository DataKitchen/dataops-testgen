import json

import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.queries.profiling_queries import COLUMN_PROFILING_FIELDS
from testgen.utils import format_field


def column_history_dialog(*args) -> None:
    st.session_state["column_history_dialog:run_id"] = None
    _column_history_dialog(*args)
    

@st.dialog(title="Column History")
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
            profiling_runs = get_profiling_runs(table_group_id, add_date)
            run_id = st.session_state.get("column_history_dialog:run_id") or profiling_runs.iloc[0]["id"]
            selected_item = get_run_column(run_id, schema_name, table_name, column_name)

    testgen_component(
        "column_profiling_history",
        props={
            "profiling_runs": [
                {
                    "run_id": format_field(run["id"]),
                    "run_date": format_field(run["profiling_starttime"]),
                } for _, run in profiling_runs.iterrows()
            ],
            "selected_item": selected_item,
        },
        on_change_handlers={
            "RunSelected": on_run_selected,
        }
    )


def on_run_selected(run_id: str) -> None:
    st.session_state["column_history_dialog:run_id"] = run_id


@st.cache_data(show_spinner=False)
def get_profiling_runs(
    table_group_id: str,
    after_date: int,
) -> pd.DataFrame:
    schema: str = st.session_state["dbschema"]
    query = f"""
    SELECT
        id::VARCHAR,
        profiling_starttime
    FROM {schema}.profiling_runs
    WHERE table_groups_id = '{table_group_id}'
       AND profiling_starttime >= TO_TIMESTAMP({after_date / 1000})
    ORDER BY profiling_starttime DESC;
    """
    return db.retrieve_data(query)


@st.cache_data(show_spinner=False)
def get_run_column(run_id: str, schema_name: str, table_name: str, column_name: str) -> dict:
    schema: str = st.session_state["dbschema"]
    query = f"""
    SELECT
        profile_run_id::VARCHAR,
        general_type,
        {COLUMN_PROFILING_FIELDS}
    FROM {schema}.profile_results
    WHERE profile_run_id = '{run_id}'
        AND schema_name = '{schema_name}'
        AND table_name = '{table_name}'
        AND column_name = '{column_name}';
    """
    results = db.retrieve_data(query)
    if not results.empty:
        # to_json converts datetimes, NaN, etc, to JSON-safe values (Note: to_dict does not)
        return json.loads(results.to_json(orient="records"))[0]
