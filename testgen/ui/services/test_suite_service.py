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


def get_test_suite_refresh_warning(table_groups_id, test_suite_name):
    if not test_suite_name:
        return False
    schema = st.session_state["dbschema"]
    row_result = test_suite_queries.get_test_suite_refresh_check(schema, table_groups_id, test_suite_name)

    test_ct = None
    unlocked_test_ct = None
    unlocked_edits_ct = None
    if row_result:
        test_ct = row_result["test_ct"]
        unlocked_test_ct = row_result["unlocked_test_ct"]
        unlocked_edits_ct = row_result["unlocked_edits_ct"]

    return test_ct, unlocked_test_ct, unlocked_edits_ct


def get_generation_set_choices():
    schema = st.session_state["dbschema"]
    dfSets = test_suite_queries.get_generation_sets(schema)
    if dfSets.empty:
        return None
    else:
        return dfSets["generation_set"].to_list()


def lock_edited_tests(test_suite_name):
    schema = st.session_state["dbschema"]
    tests_locked = test_suite_queries.lock_edited_tests(schema, test_suite_name)
    return tests_locked
