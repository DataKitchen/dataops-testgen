import streamlit as st

import testgen.ui.queries.table_group_queries as table_group_queries
import testgen.ui.services.connection_service as connection_service
from testgen.common.database.database_service import RetrieveDBResultsToDictList


def get_by_id(table_group_id: str):
    schema = st.session_state["dbschema"]
    return table_group_queries.get_by_id(schema, table_group_id)


def get_by_connection(project_code, connection_id):
    schema = st.session_state["dbschema"]
    return table_group_queries.get_by_connection(schema, project_code, connection_id)


def edit(table_group):
    schema = st.session_state["dbschema"]
    table_group_queries.edit(schema, table_group)


def add(table_group):
    schema = st.session_state["dbschema"]
    table_group_queries.add(schema, table_group)


def delete(table_group_ids, table_group_names, dry_run=False):  # noqa ARG001
    schema = st.session_state["dbschema"]

    # TODO: avoid deletion of used table groups
    # usage_result = table_group_queries.get_table_group_usage(schema, table_group_ids, table_group_names)
    # can_be_deleted = usage_result.empty
    can_be_deleted = True

    if not dry_run and can_be_deleted:
        table_group_queries.delete(schema, table_group_ids)
    return can_be_deleted


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
