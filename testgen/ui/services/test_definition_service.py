import streamlit as st

import testgen.ui.queries.test_definition_queries as test_definition_queries
import testgen.ui.services.connection_service as connection_service
import testgen.ui.services.database_service as database_service
import testgen.ui.services.table_group_service as table_group_service
import testgen.ui.services.test_run_service as test_run_service


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


def delete(test_definition_ids, dry_run=False):
    schema = st.session_state["dbschema"]
    usage_result = test_definition_queries.get_test_definition_usage(schema, test_definition_ids)
    can_be_deleted = usage_result.empty
    if not dry_run and can_be_deleted:
        test_definition_queries.delete(schema, test_definition_ids)
    return can_be_deleted


def cascade_delete(test_suite_ids: list[str]):
    schema = st.session_state["dbschema"]
    test_run_service.cascade_delete(test_suite_ids)
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
        sql_query,
    )
