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


def get_table_group_preview(project_code: str, connection: dict | None, table_group: dict) -> dict:
    table_group_preview = {
        "schema": table_group["table_group_schema"],
        "tables": set(),
        "column_count": 0,
        "success": True,
        "message": None,
    }
    if connection:
        try:
            table_group_results = test_table_group(table_group, connection, project_code)

            for column in table_group_results:
                table_group_preview["schema"] = column["table_schema"]
                table_group_preview["tables"].add(column["table_name"])
                table_group_preview["column_count"] += 1

            if len(table_group_results) <= 0:
                table_group_preview["success"] = False
                table_group_preview["message"] = (
                    "No tables found matching the criteria. Please check the Table Group configuration"
                    " or the database permissions."
                )
        except Exception as error:
            table_group_preview["success"] = False
            table_group_preview["message"] = error.args[0]
    else:
        table_group_preview["success"] = False
        table_group_preview["message"] = "No connection selected. Please select a connection to preview the Table Group."

    table_group_preview["tables"] = list(table_group_preview["tables"])
    return table_group_preview


def test_table_group(table_group, connection, project_code):
    connection_id = str(connection["connection_id"])

    # get table group data
    table_group_schema = table_group["table_group_schema"]
    table_group_id = table_group["id"]
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

    return table_group_results


def get_profiling_table_set_with_quotes(profiling_table_set):
    if not profiling_table_set:
        return profiling_table_set

    aux_list = []
    split = profiling_table_set.split(",")
    for item in split:
        aux_list.append(f"'{item.strip()}'")
    profiling_table_set = ",".join(aux_list)
    return profiling_table_set
