import streamlit as st

import testgen.ui.queries.table_group_queries as table_group_queries
import testgen.ui.services.connection_service as connection_service
import testgen.ui.services.test_suite_service as test_suite_service
from testgen.common.database.database_service import RetrieveDBResultsToDictList
from testgen.common.models.scores import ScoreDefinition


def get_by_id(table_group_id: str):
    schema = st.session_state["dbschema"]
    return table_group_queries.get_by_id(schema, table_group_id).iloc[0]


def get_by_connection(project_code, connection_id):
    schema = st.session_state["dbschema"]
    return table_group_queries.get_by_connection(schema, project_code, connection_id)


def get_all(project_code: str):
    schema = st.session_state["dbschema"]
    return table_group_queries.get_all(schema, project_code)


def edit(table_group):
    schema = st.session_state["dbschema"]
    table_group_queries.edit(schema, table_group)


def add(table_group: dict) -> str:
    schema = st.session_state["dbschema"]
    table_group_id = table_group_queries.add(schema, table_group)
    if table_group.get("add_scorecard_definition", True):
        ScoreDefinition.from_table_group(table_group).save()
    return table_group_id


def cascade_delete(table_group_names, dry_run=False):
    schema = st.session_state["dbschema"]
    test_suite_ids = get_test_suite_ids_by_table_group_names(table_group_names)

    can_be_deleted = not any(
        (
            table_group_has_dependencies(table_group_names),
            test_suite_service.has_test_suite_dependencies(test_suite_ids),
        )
    )

    if not dry_run:
        test_suite_service.cascade_delete(test_suite_ids)
        table_group_queries.cascade_delete(schema, table_group_names)
    return can_be_deleted


def table_group_has_dependencies(table_group_names):
    if not table_group_names:
        return False
    schema = st.session_state["dbschema"]
    return not table_group_queries.get_table_group_dependencies(schema, table_group_names).empty


def are_table_groups_in_use(table_group_names: list[str]):
    if not table_group_names:
        return False

    schema = st.session_state["dbschema"]

    test_suite_ids = get_test_suite_ids_by_table_group_names(table_group_names)
    test_suites_in_use = test_suite_service.are_test_suites_in_use(test_suite_ids)

    table_groups_in_use_result = table_group_queries.get_table_group_usage(schema, table_group_names)
    table_groups_in_use = not table_groups_in_use_result.empty

    return test_suites_in_use or table_groups_in_use


def is_table_group_used(table_group_id: str) -> bool:
    schema = st.session_state["dbschema"]
    test_suite_ids = table_group_queries.get_test_suite_ids_by_table_group_id(schema, table_group_id)
    proling_run_ids = table_group_queries.get_profiling_run_ids_by_table_group_id(schema, table_group_id)

    return len(test_suite_ids) + len(proling_run_ids) > 0


def get_test_suite_ids_by_table_group_names(table_group_names):
    if not table_group_names:
        return []
    schema = st.session_state["dbschema"]
    result = table_group_queries.get_test_suite_ids_by_table_group_names(schema, table_group_names)
    return result.to_dict()["id"].values()
