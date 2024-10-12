import streamlit as st

import testgen.ui.queries.test_run_queries as test_run_queries


def cascade_delete(test_suite_ids):
    schema = st.session_state["dbschema"]
    test_run_queries.cascade_delete(schema, test_suite_ids)


def update_status(test_run_id, status):
    schema = st.session_state["dbschema"]
    test_run_queries.update_status(schema, test_run_id, status)
