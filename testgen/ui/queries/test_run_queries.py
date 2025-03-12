from datetime import datetime
from typing import NamedTuple

import streamlit as st

import testgen.common.date_service as date_service
import testgen.ui.services.database_service as db
from testgen.common.models import get_current_session


def cascade_delete(test_suite_ids: list[str]) -> None:
    if not test_suite_ids:
        raise ValueError("No Test Suite is specified.")

    schema: str = st.session_state["dbschema"]
    ids_str = ", ".join([f"'{item}'" for item in test_suite_ids])
    sql = f"""
        DELETE
            FROM {schema}.working_agg_cat_results
            WHERE test_run_id in (select id from {schema}.test_runs where test_suite_id in ({ids_str}));
        DELETE
            FROM {schema}.working_agg_cat_tests
            WHERE test_run_id in (select id from {schema}.test_runs where test_suite_id in ({ids_str}));
        DELETE FROM {schema}.test_runs WHERE test_suite_id in ({ids_str});
        DELETE FROM {schema}.test_results WHERE test_suite_id in ({ids_str});
    """
    db.execute_sql(sql)
    st.cache_data.clear()


def update_status(test_run_id: str, status: str) -> None:
    if not all([test_run_id, status]):
        raise ValueError("Missing query parameters.")

    schema: str = st.session_state["dbschema"]
    now = date_service.get_now_as_string()

    sql = f"""
        UPDATE {schema}.test_runs
           SET status = '{status}',
               test_endtime = '{now}'
         WHERE id = '{test_run_id}'::UUID;
    """
    db.execute_sql(sql)
    st.cache_data.clear()


def cancel_all_running() -> None:
    schema: str = db.get_schema()
    db.execute_sql(f"""
    UPDATE {schema}.test_runs
        SET status = 'Cancelled'
        WHERE status = 'Running';
    """)


class LatestTestRun(NamedTuple):
    id: str
    run_time: datetime


def get_latest_run_date(project_code: str) -> LatestTestRun | None:
    session = get_current_session()
    result = session.execute(
        """
        SELECT runs.id, test_starttime
        FROM test_runs AS runs
        INNER JOIN test_suites AS suite ON (suite.id = runs.test_suite_id)
        WHERE project_code = :project_code
            AND status = 'Complete'
        ORDER BY test_starttime DESC
        LIMIT 1
        """,
        params={"project_code": project_code},
    )
    if result and (latest_run := result.first()):
        return LatestTestRun(str(latest_run.id), latest_run.test_starttime)
    return None
