import streamlit as st

import testgen.ui.services.database_service as db
from testgen.common import date_service
from testgen.common.models import get_current_session


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


def cascade_delete_multiple_profiling_runs(profiling_run_ids: list[str]) -> None:
    session = get_current_session()

    if not profiling_run_ids:
        raise ValueError("No profiling run is specified.")

    params = {f"id_{idx}": value for idx, value in enumerate(profiling_run_ids)}
    param_keys = [f":{slot}" for slot in params.keys()]

    with session.begin():
        session.execute(f"DELETE FROM profile_pair_rules WHERE profile_run_id IN ({', '.join(param_keys)})", params=params)
        session.execute(f"DELETE FROM profile_anomaly_results WHERE profile_run_id IN ({', '.join(param_keys)})", params=params)
        session.execute(f"DELETE FROM profile_results WHERE profile_run_id IN ({', '.join(param_keys)})", params=params)
        session.execute(f"DELETE FROM profiling_runs WHERE id IN ({', '.join(param_keys)})", params=params)
        session.commit()

    st.cache_data.clear()
