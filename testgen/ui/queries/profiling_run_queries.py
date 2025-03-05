import streamlit as st

import testgen.ui.services.database_service as db
from testgen.common import date_service


def update_status(profile_run_id: str, status: str) -> None:
    schema: str = st.session_state["dbschema"]
    now = date_service.get_now_as_string()

    sql = f"""
    UPDATE {schema}.profiling_runs
    SET status = '{status}',
        profiling_endtime = '{now}'
    WHERE id = '{profile_run_id}'::UUID;
    """
    db.execute_sql(sql)
    st.cache_data.clear()


def cancel_all_running() -> None:
    schema: str = db.get_schema()
    db.execute_sql(f"""
    UPDATE {schema}.profiling_runs
        SET status = 'Cancelled'
        WHERE status = 'Running';
    """)
