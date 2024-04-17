import streamlit as st

import testgen.ui.queries.test_suite_queries as test_suite_queries


def get_by_table_group(project_code, table_group_id):
    schema = st.session_state["dbschema"]
    return test_suite_queries.get_by_table_group(schema, project_code, table_group_id)


def edit(test_suite):
    schema = st.session_state["dbschema"]
    test_suite_queries.edit(schema, test_suite)


def add(test_suite):
    schema = st.session_state["dbschema"]
    test_suite_queries.add(schema, test_suite)


def delete(test_suite_ids, test_suite_names, dry_run=False):
    schema = st.session_state["dbschema"]
    usage_result = test_suite_queries.get_test_suite_usage(schema, test_suite_names)
    can_be_deleted = usage_result.empty
    if not dry_run and can_be_deleted:
        test_suite_queries.delete(schema, test_suite_ids)
    return can_be_deleted
