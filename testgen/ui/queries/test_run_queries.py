import streamlit as st

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
