import streamlit as st

import testgen.ui.queries.test_definition_queries as test_definition_queries
import testgen.ui.services.connection_service as connection_service
import testgen.ui.services.database_service as database_service
import testgen.ui.services.table_group_service as table_group_service
from testgen.ui.queries import test_run_queries


def update_attribute(test_definition_ids, attribute, value):
    schema = st.session_state["dbschema"]
    raw_value = "Y" if value else "N"
    test_definition_queries.update_attribute(schema, test_definition_ids, attribute, raw_value)


def get_test_definitions(
    project_code=None, test_suite=None, table_name=None, column_name=None, test_definition_ids=None
):
    schema = st.session_state["dbschema"]
    return test_definition_queries.get_test_definitions(
        schema, project_code, test_suite, table_name, column_name, test_definition_ids
    )


def get_test_definition(db_schema, test_def_id):
    str_sql = f"""
           SELECT d.id::VARCHAR, tt.test_name_short as test_name, tt.test_name_long as full_name,
                  tt.test_description as description, tt.usage_notes,
                  d.column_name,
                  d.baseline_value, d.baseline_ct, d.baseline_avg, d.baseline_sd, d.threshold_value,
                  d.subset_condition, d.groupby_names, d.having_condition, d.match_schema_name,
                  d.match_table_name, d.match_column_names, d.match_subset_condition,
                  d.match_groupby_names, d.match_having_condition,
                  d.window_date_column, d.window_days::VARCHAR as window_days,
                  d.custom_query,
                  d.severity, tt.default_severity,
                  d.test_active, d.lock_refresh, d.last_manual_update
             FROM {db_schema}.test_definitions d
           INNER JOIN {db_schema}.test_types tt
              ON (d.test_type = tt.test_type)
            WHERE d.id = '{test_def_id}';
    """
    return database_service.retrieve_data(str_sql)


def delete(test_definition_ids, dry_run=False):
    schema = st.session_state["dbschema"]
    usage_result = test_definition_queries.get_test_definition_usage(schema, test_definition_ids)
    can_be_deleted = usage_result.empty
    if not dry_run and can_be_deleted:
        test_definition_queries.delete(schema, test_definition_ids)
    return can_be_deleted


def cascade_delete(test_suite_ids: list[str]):
    schema = st.session_state["dbschema"]
    test_run_queries.cascade_delete(test_suite_ids)
    test_definition_queries.cascade_delete(schema, test_suite_ids)


def add(test_definition):
    schema = st.session_state["dbschema"]
    prepare_to_persist(test_definition)
    test_definition_queries.add(schema, test_definition)


def update(test_definition):
    schema = st.session_state["dbschema"]
    prepare_to_persist(test_definition)
    return test_definition_queries.update(schema, test_definition)


def prepare_to_persist(test_definition):
    # severity
    if test_definition["severity"] and test_definition["severity"].startswith("Inherited"):
        test_definition["severity"] = None

    test_definition["export_to_observability"] = prepare_boolean_for_update(
        test_definition["export_to_observability_raw"]
    )
    test_definition["lock_refresh"] = prepare_boolean_for_update(test_definition["lock_refresh"])
    test_definition["test_active"] = prepare_boolean_for_update(test_definition["test_active"])

    if test_definition["custom_query"] is not None:
        test_definition["custom_query"] = test_definition["custom_query"].strip()
        if test_definition["custom_query"].endswith(";"):
            test_definition["custom_query"] = test_definition["custom_query"][:-1]

    empty_if_null(test_definition)


def empty_if_null(test_definition):
    for k, v in test_definition.items():
        if v is None:
            test_definition[k] = ""


def prepare_boolean_for_update(value):
    if "Yes" == value or "Y" == value or value is True:
        return "Y"
    elif "No" == value or "N" == value or value is False:
        return "N"
    else:
        return None


def validate_test(test_definition):
    schema = test_definition["schema_name"]
    table_name = test_definition["table_name"]

    if test_definition["test_type"] == "Condition_Flag":
        condition = test_definition["custom_query"]
        sql_query = f"""SELECT COALESCE(CAST(SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) AS VARCHAR(1000) ) || '|' ,'<NULL>|') FROM {schema}.{table_name}"""
    else:
        sql_query = test_definition["custom_query"]
        sql_query = sql_query.replace("{DATA_SCHEMA}", schema)

    table_group_id = test_definition["table_groups_id"]
    table_group = table_group_service.get_by_id(table_group_id)

    connection_id = table_group["connection_id"]

    connection = connection_service.get_by_id(connection_id, hide_passwords=False)

    database_service.retrieve_target_db_data(
        connection["sql_flavor"],
        connection["project_host"],
        connection["project_port"],
        connection["project_db"],
        connection["project_user"],
        connection["password"],
        connection["url"],
        connection["connect_by_url"],
        connection["connect_by_key"],
        connection["private_key"],
        connection["private_key_passphrase"],
        connection["http_path"],
        sql_query,
    )


def move(test_definitions, target_table_group, target_test_suite):
    schema = st.session_state["dbschema"]
    test_definition_queries.move(schema, test_definitions, target_table_group, target_test_suite)



def copy(test_definitions, target_table_group, target_test_suite):
    schema = st.session_state["dbschema"]
    test_definition_queries.copy(schema, test_definitions, target_table_group, target_test_suite)


def get_test_definitions_collision(test_definitions, target_table_group, target_test_suite):
    schema = st.session_state["dbschema"]
    return test_definition_queries.get_test_definitions_collision(schema, test_definitions, target_table_group, target_test_suite)
