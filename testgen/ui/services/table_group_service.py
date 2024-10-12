import streamlit as st

import testgen.ui.queries.table_group_queries as table_group_queries
import testgen.ui.services.connection_service as connection_service
import testgen.ui.services.test_suite_service as test_suite_service
from testgen.common.database.database_service import RetrieveDBResultsToDictList


def get_by_id(table_group_id: str):
    schema = st.session_state["dbschema"]
    return table_group_queries.get_by_id(schema, table_group_id).iloc[0]


def get_by_connection(project_code, connection_id):
    schema = st.session_state["dbschema"]
    return table_group_queries.get_by_connection(schema, project_code, connection_id)


def edit(table_group):
    schema = st.session_state["dbschema"]
    table_group_queries.edit(schema, table_group)


def add(table_group):
    schema = st.session_state["dbschema"]
    table_group_queries.add(schema, table_group)


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


def are_table_groups_in_use(table_group_names):
    if not table_group_names:
        return False

    schema = st.session_state["dbschema"]

    test_suite_ids = get_test_suite_ids_by_table_group_names(table_group_names)
    test_suites_in_use = test_suite_service.are_test_suites_in_use(test_suite_ids)

    table_groups_in_use_result = table_group_queries.get_table_group_usage(schema, table_group_names)
    table_groups_in_use = not table_groups_in_use_result.empty

    return test_suites_in_use or table_groups_in_use


def get_test_suite_ids_by_table_group_names(table_group_names):
    if not table_group_names:
        return []
    schema = st.session_state["dbschema"]
    result = table_group_queries.get_test_suite_ids_by_table_group_names(schema, table_group_names)
    return result.to_dict()["id"].values()


def test_table_group(table_group, connection_id, project_code):
    # get connection data
    connection = connection_service.get_by_id(connection_id, hide_passwords=False)
    connection_id = str(connection["connection_id"])

    # get table group data
    table_group_schema = table_group["table_group_schema"]
    table_group_id = table_group["id"]
    project_qc_schema = connection["project_qc_schema"]
    profiling_table_set = table_group["profiling_table_set"]
    profiling_include_mask = table_group["profiling_include_mask"]
    profiling_exclude_mask = table_group["profiling_exclude_mask"]
    profile_id_column_mask = table_group["profile_id_column_mask"]
    profile_sk_column_mask = table_group["profile_sk_column_mask"]
    profile_use_sampling = "Y" if table_group["profile_use_sampling"] else "N"
    profile_sample_percent = table_group["profile_sample_percent"]
    profile_sample_min_count = table_group["profile_sample_min_count"]

    clsProfiling = connection_service.init_profiling_sql(project_code, connection, table_group_schema)

    # Set General Parms
    clsProfiling.table_groups_id = table_group_id
    clsProfiling.connection_id = connection_id
    clsProfiling.parm_do_sample = "N"
    clsProfiling.parm_sample_size = 0
    clsProfiling.parm_vldb_flag = "N"
    clsProfiling.parm_do_freqs = "Y"
    clsProfiling.parm_max_freq_length = 25
    clsProfiling.parm_do_patterns = "Y"
    clsProfiling.parm_max_pattern_length = 25
    clsProfiling.profile_run_id = ""
    clsProfiling.data_qc_schema = project_qc_schema
    clsProfiling.data_schema = table_group_schema
    clsProfiling.parm_table_set = get_profiling_table_set_with_quotes(profiling_table_set)
    clsProfiling.parm_table_include_mask = profiling_include_mask
    clsProfiling.parm_table_exclude_mask = profiling_exclude_mask
    clsProfiling.profile_id_column_mask = profile_id_column_mask
    clsProfiling.profile_sk_column_mask = profile_sk_column_mask
    clsProfiling.profile_use_sampling = profile_use_sampling
    clsProfiling.profile_sample_percent = profile_sample_percent
    clsProfiling.profile_sample_min_count = profile_sample_min_count

    query = clsProfiling.GetDDFQuery()
    table_group_results = RetrieveDBResultsToDictList("PROJECT", query)

    qc_results = connection_service.test_qc_connection(project_code, connection, init_profiling=False)

    return table_group_results, qc_results


def get_profiling_table_set_with_quotes(profiling_table_set):
    if not profiling_table_set:
        return profiling_table_set

    aux_list = []
    split = profiling_table_set.split(",")
    for item in split:
        aux_list.append(f"'{item}'")
    profiling_table_set = ",".join(aux_list)
    return profiling_table_set
