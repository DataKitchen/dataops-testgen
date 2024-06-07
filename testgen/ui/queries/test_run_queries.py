import streamlit as st

import testgen.common.date_service as date_service
import testgen.ui.services.database_service as db


def cascade_delete(schema: str, test_suite_names: list[str]) -> None:
    if test_suite_names is None or len(test_suite_names) == 0:
        raise ValueError("No Test Suite is specified.")

    items = [f"'{item}'" for item in test_suite_names]
    sql = f"""delete from {schema}.working_agg_cat_results where test_suite in ({",".join(items)});
delete from {schema}.working_agg_cat_tests where test_suite in ({",".join(items)});
delete from {schema}.test_runs where test_suite in ({",".join(items)});
delete from {schema}.test_results where test_suite in ({",".join(items)});
delete from {schema}.execution_queue where test_suite in ({",".join(items)});"""
    db.execute_sql(sql)
    st.cache_data.clear()


def update_status(schema: str, test_run_id: str, status: str) -> None:
    if not all([test_run_id, status]):
        raise ValueError("Missing query parameters.")

    now = date_service.get_now_as_string()

    sql = f"""UPDATE {schema}.test_runs
SET status = '{status}',
    test_endtime = '{now}'
where id = '{test_run_id}' :: UUID;"""
    db.execute_sql(sql)
    st.cache_data.clear()
