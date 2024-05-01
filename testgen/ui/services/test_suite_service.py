import streamlit as st

import testgen.ui.queries.test_suite_queries as test_suite_queries
import testgen.ui.services.test_definition_service as test_definition_service


def get_by_table_group(project_code, table_group_id):
    schema = st.session_state["dbschema"]
    return test_suite_queries.get_by_table_group(schema, project_code, table_group_id)


def edit(test_suite):
    schema = st.session_state["dbschema"]
    test_suite_queries.edit(schema, test_suite)


def add(test_suite):
    schema = st.session_state["dbschema"]
    test_suite_queries.add(schema, test_suite)


def cascade_delete(test_suite_names, dry_run=False):
    if not test_suite_names:
        return True
    schema = st.session_state["dbschema"]
    can_be_deleted = not has_test_suite_dependencies(schema, test_suite_names)
    if not dry_run:
        test_definition_service.cascade_delete(test_suite_names)
        test_suite_queries.cascade_delete(schema, test_suite_names)
    return can_be_deleted


def has_test_suite_dependencies(schema, test_suite_names):
    if not test_suite_names:
        return False
    return not test_suite_queries.get_test_suite_dependencies(schema, test_suite_names).empty


def are_test_suites_in_use(test_suite_names):
    if not test_suite_names:
        return False
    schema = st.session_state["dbschema"]
    usage_result = test_suite_queries.get_test_suite_usage(schema, test_suite_names)
    return not usage_result.empty
