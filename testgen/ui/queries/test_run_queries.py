import streamlit as st

import testgen.common.date_service as date_service
import testgen.ui.services.database_service as db


def cascade_delete(schema: str, test_suite_ids: list[str]) -> None:
    if not test_suite_ids:
        raise ValueError("No Test Suite is specified.")

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


def update_status(schema: str, test_run_id: str, status: str) -> None:
    if not all([test_run_id, status]):
        raise ValueError("Missing query parameters.")

    now = date_service.get_now_as_string()

    sql = f"""
        UPDATE {schema}.test_runs
           SET status = '{status}',
               test_endtime = '{now}'
         WHERE id = '{test_run_id}'::UUID;
    """
    db.execute_sql(sql)
    st.cache_data.clear()
