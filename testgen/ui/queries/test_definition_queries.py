import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db
from testgen.common.models import get_current_session, with_database_session


def update_attribute(schema, test_definition_ids, attribute, value):
    sql = f"""
    WITH selected as (
        SELECT UNNEST(ARRAY [{", ".join([ f"'{item}'" for item in test_definition_ids ])}]) AS id
    )
    UPDATE {schema}.test_definitions
    SET {attribute}='{value}'
    FROM {schema}.test_definitions td
        INNER JOIN selected ON (td.id = selected.id::UUID)
    WHERE td.id = test_definitions.id;
    """
    db.execute_sql_raw(sql)
    st.cache_data.clear()


@st.cache_data(show_spinner=False)
@with_database_session
def get_test_definitions(_, project_code, test_suite, table_name, column_name, test_type, test_definition_ids: list[str] | None):
    db_session = get_current_session()
    params = {}
    order_by = "ORDER BY d.schema_name, d.table_name, d.column_name, d.test_type"
    filters = ""

    if project_code:
        filters += " AND s.project_code = :project_code"
        params["project_code"] = project_code

    if test_suite:
        filters += " AND s.test_suite = :test_suite"
        params["test_suite"] = test_suite

    if test_definition_ids:
        test_definition_params = {f"test_definition_id_{idx}": status for idx, status in enumerate(test_definition_ids)}
        filters += f" AND d.id IN ({', '.join([f':{p}' for p in test_definition_params.keys()])})"
        params.update(test_definition_params)

    if table_name:
        filters += " AND d.table_name = :table_name"
        params["table_name"] = table_name

    if column_name:
        filters += " AND d.column_name ILIKE :column_name"
        params["column_name"] = column_name
    
    if test_type:
        filters += " AND d.test_type = :test_type"
        params["test_type"] = test_type

    sql = f"""
    SELECT
        d.schema_name, d.table_name, d.column_name, t.test_name_short, t.test_name_long,
        d.id::VARCHAR(50),
        s.project_code, d.table_groups_id::VARCHAR(50), s.test_suite, d.test_suite_id::VARCHAR,
        d.test_type, d.cat_test_id::VARCHAR(50),
        d.test_active,
        CASE WHEN d.test_active = 'Y' THEN 'Yes' ELSE 'No' END as test_active_display,
        d.lock_refresh,
        CASE WHEN d.lock_refresh = 'Y' THEN 'Yes' ELSE 'No' END as lock_refresh_display,
        t.test_scope,
        d.test_description,
        d.profiling_as_of_date,
        d.last_manual_update,
        d.severity, COALESCE(d.severity, s.severity, t.default_severity) as urgency,
        d.export_to_observability as export_to_observability_raw,
        CASE
            WHEN d.export_to_observability = 'Y' THEN 'Yes'
            WHEN d.export_to_observability = 'N' THEN 'No'
            WHEN d.export_to_observability IS NULL AND s.export_to_observability = 'Y' THEN 'Inherited (Yes)'
            ELSE 'Inherited (No)'
        END as export_to_observability,
        -- test_action,
        d.threshold_value, COALESCE(t.measure_uom_description, t.measure_uom) as export_uom,
        d.baseline_ct, d.baseline_unique_ct, d.baseline_value,
        d.baseline_value_ct, d.baseline_sum, d.baseline_avg, d.baseline_sd,
        d.lower_tolerance, d.upper_tolerance,
        d.subset_condition,
        d.groupby_names, d.having_condition, d.window_date_column, d.window_days,
        d.match_schema_name, d.match_table_name, d.match_column_names,
        d.match_subset_condition, d.match_groupby_names, d.match_having_condition,
        d.skip_errors, d.custom_query,
        COALESCE(d.test_description, t.test_description) as final_test_description,
        t.default_parm_columns, t.selection_criteria,
        d.profile_run_id::VARCHAR(50), d.test_action, d.test_definition_status,
        d.watch_level, d.check_result, d.last_auto_gen_date,
        d.test_mode
    FROM test_definitions d
    INNER JOIN test_types t ON (d.test_type = t.test_type)
    INNER JOIN test_suites s ON (d.test_suite_id = s.id)
    WHERE True
    {filters}
    {order_by}
    """

    results = db_session.execute(sql, params=params)
    columns = [column.name for column in results.cursor.description]

    return pd.DataFrame(list(results), columns=columns)


def update(schema, test_definition):
    sql = f"""UPDATE {schema}.test_definitions
                SET
                    cat_test_id = {test_definition["cat_test_id"]},
                    --last_auto_gen_date = NULLIF('test_definition["last_auto_gen_date"]', ''),
                    --profiling_as_of_date = NULLIF('test_definition["profiling_as_of_date"]', ''),
                    last_manual_update = CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
                    skip_errors = {test_definition["skip_errors"]},
                    custom_query = NULLIF($${test_definition["custom_query"]}$$, ''),
                    test_definition_status = NULLIF('{test_definition["test_definition_status"]}', ''),
                    export_to_observability = NULLIF('{test_definition["export_to_observability"]}', ''),
                    column_name = NULLIF($${test_definition["column_name"]}$$, ''),
                    watch_level = NULLIF('{test_definition["watch_level"]}', ''),
                    table_groups_id = '{test_definition["table_groups_id"]}'::UUID,
                    """

    if test_definition["profile_run_id"]:
        sql += f"profile_run_id = '{test_definition['profile_run_id']}'::UUID,\n"
    if test_definition["test_suite_id"]:
        sql += f"test_suite_id = '{test_definition['test_suite_id']}'::UUID,\n"

    sql += f"""     test_type = NULLIF('{test_definition["test_type"]}', ''),
                    test_description = NULLIF($${test_definition["test_description"]}$$, ''),
                    test_action = NULLIF('{test_definition["test_action"]}', ''),
                    test_mode = NULLIF('{test_definition["test_mode"]}', ''),
                    lock_refresh = NULLIF('{test_definition["lock_refresh"]}', ''),
                    schema_name = NULLIF('{test_definition["schema_name"]}', ''),
                    table_name = NULLIF('{test_definition["table_name"]}', ''),
                    test_active = NULLIF('{test_definition["test_active"]}', ''),
                    severity = NULLIF('{test_definition["severity"]}', ''),
                    check_result = NULLIF('{test_definition["check_result"]}', ''),
                    baseline_ct = NULLIF('{test_definition["baseline_ct"]}', ''),
                    baseline_unique_ct = NULLIF('{test_definition["baseline_unique_ct"]}', ''),
                    baseline_value = NULLIF($${test_definition["baseline_value"]}$$, ''),
                    baseline_value_ct = NULLIF('{test_definition["baseline_value_ct"]}', ''),
                    threshold_value = NULLIF($${test_definition["threshold_value"]}$$, ''),
                    baseline_sum = NULLIF('{test_definition["baseline_sum"]}', ''),
                    baseline_avg = NULLIF('{test_definition["baseline_avg"]}', ''),
                    baseline_sd = NULLIF('{test_definition["baseline_sd"]}', ''),
                    lower_tolerance = NULLIF('{test_definition["lower_tolerance"]}', ''),
                    upper_tolerance = NULLIF('{test_definition["upper_tolerance"]}', ''),
                    subset_condition = NULLIF($${test_definition["subset_condition"]}$$, ''),
                    groupby_names = NULLIF($${test_definition["groupby_names"]}$$, ''),
                    having_condition = NULLIF($${test_definition["having_condition"]}$$, ''),
                    window_date_column = NULLIF('{test_definition["window_date_column"]}', ''),
                    match_schema_name = NULLIF('{test_definition["match_schema_name"]}', ''),
                    match_table_name = NULLIF('{test_definition["match_table_name"]}', ''),
                    match_column_names = NULLIF($${test_definition["match_column_names"]}$$, ''),
                    match_subset_condition = NULLIF($${test_definition["match_subset_condition"]}$$, ''),
                    match_groupby_names = NULLIF($${test_definition["match_groupby_names"]}$$, ''),
                    match_having_condition = NULLIF($${test_definition["match_having_condition"]}$$, ''),
                    window_days = COALESCE({test_definition["window_days"]}, 0)
                where
                    id = '{test_definition["id"]}'
                ;
                """
    db.execute_sql(sql)
    st.cache_data.clear()


def add(schema, test_definition):
    sql = f"""INSERT INTO {schema}.test_definitions
                (
                    --cat_test_id,
                    --last_auto_gen_date,
                    --profiling_as_of_date,
                    last_manual_update,
                    skip_errors,
                    custom_query,
                    test_definition_status,
                    export_to_observability,
                    column_name,
                    watch_level,
                    table_groups_id,
                    profile_run_id,
                    test_type,
                    test_suite_id,
                    test_description,
                    test_action,
                    test_mode,
                    lock_refresh,
                    schema_name,
                    table_name,
                    test_active,
                    severity,
                    check_result,
                    baseline_ct,
                    baseline_unique_ct,
                    baseline_value,
                    baseline_value_ct,
                    threshold_value,
                    baseline_sum,
                    baseline_avg,
                    baseline_sd,
                    lower_tolerance,
                    upper_tolerance,
                    subset_condition,
                    groupby_names,
                    having_condition,
                    window_date_column,
                    match_schema_name,
                    match_table_name,
                    match_column_names,
                    match_subset_condition,
                    match_groupby_names,
                    match_having_condition,
                    window_days
                )
                SELECT
                    --{test_definition["cat_test_id"]} as cat_test_id,
                    --NULLIF('test_definition["last_auto_gen_date"]', '') as last_auto_gen_date,
                    --NULLIF('test_definition["profiling_as_of_date"]', '') as profiling_as_of_date,
                    CURRENT_TIMESTAMP AT TIME ZONE 'UTC' as last_manual_update,
                    {test_definition["skip_errors"]} as skip_errors,
                    NULLIF($${test_definition["custom_query"]}$$, '') as custom_query,
                    NULLIF('{test_definition["test_definition_status"]}', '') as test_definition_status,
                    NULLIF('{test_definition["export_to_observability"]}', '') as export_to_observability,
                    NULLIF('{test_definition["column_name"]}', '') as column_name,
                    NULLIF('{test_definition["watch_level"]}', '') as watch_level,
                    '{test_definition["table_groups_id"]}'::UUID as table_groups_id,
                    NULL AS profile_run_id,
                    NULLIF('{test_definition["test_type"]}', '') as test_type,
                    '{test_definition["test_suite_id"]}'::UUID as test_suite_id,
                    NULLIF('{test_definition["test_description"]}', '') as test_description,
                    NULLIF('{test_definition["test_action"]}', '') as test_action,
                    NULLIF('{test_definition["test_mode"]}', '') as test_mode,
                    NULLIF('{test_definition["lock_refresh"]}', '') as lock_refresh,
                    NULLIF('{test_definition["schema_name"]}', '') as schema_name,
                    NULLIF('{test_definition["table_name"]}', '') as table_name,
                    NULLIF('{test_definition["test_active"]}', '') as test_active,
                    NULLIF('{test_definition["severity"]}', '') as severity,
                    NULLIF('{test_definition["check_result"]}', '') as check_result,
                    NULLIF('{test_definition["baseline_ct"]}', '') as baseline_ct,
                    NULLIF('{test_definition["baseline_unique_ct"]}', '') as baseline_unique_ct,
                    NULLIF($${test_definition["baseline_value"]}$$, '') as baseline_value,
                    NULLIF($${test_definition["baseline_value_ct"]}$$, '') as baseline_value_ct,
                    NULLIF($${test_definition["threshold_value"]}$$, '') as threshold_value,
                    NULLIF($${test_definition["baseline_sum"]}$$, '') as baseline_sum,
                    NULLIF('{test_definition["baseline_avg"]}', '') as baseline_avg,
                    NULLIF('{test_definition["baseline_sd"]}', '') as baseline_sd,
                    NULLIF('{test_definition["lower_tolerance"]}', '') as lower_tolerance,
                    NULLIF('{test_definition["upper_tolerance"]}', '') as upper_tolerance,
                    NULLIF($${test_definition["subset_condition"]}$$, '') as subset_condition,
                    NULLIF($${test_definition["groupby_names"]}$$, '') as groupby_names,
                    NULLIF($${test_definition["having_condition"]}$$, '') as having_condition,
                    NULLIF('{test_definition["window_date_column"]}', '') as window_date_column,
                    NULLIF('{test_definition["match_schema_name"]}', '') as match_schema_name,
                    NULLIF('{test_definition["match_table_name"]}', '') as match_table_name,
                    NULLIF($${test_definition["match_column_names"]}$$, '') as match_column_names,
                    NULLIF($${test_definition["match_subset_condition"]}$$, '') as match_subset_condition,
                    NULLIF($${test_definition["match_groupby_names"]}$$, '') as match_groupby_names,
                    NULLIF($${test_definition["match_having_condition"]}$$, '') as match_having_condition,
                    COALESCE({test_definition["window_days"]}, 0) as window_days
                ;
                """
    db.execute_sql(sql)
    st.cache_data.clear()


def delete(schema, test_definition_ids):
    if test_definition_ids is None or len(test_definition_ids) == 0:
        raise ValueError("No Test Definition is specified.")

    items = [f"'{item}'" for item in test_definition_ids]
    sql = f"""DELETE FROM {schema}.test_definitions WHERE id in ({",".join(items)})"""
    db.execute_sql(sql)
    st.cache_data.clear()


def cascade_delete(schema, test_suite_ids):
    if not test_suite_ids:
        raise ValueError("No Test Suite is specified.")

    ids_str = ", ".join([f"'{item}'" for item in test_suite_ids])
    sql = f"""
        DELETE FROM {schema}.test_definitions WHERE test_suite_id in ({ids_str})
    """
    db.execute_sql(sql)
    st.cache_data.clear()


def move(schema, test_definitions, target_table_group, target_test_suite, target_table_column=None):
    if target_table_column is not None:
        update_target_table_column = f"""
        column_name = '{target_table_column['column_name']}', 
        table_name = '{target_table_column['table_name']}', 
        """
    else:
        update_target_table_column = "" 
    sql = f"""
    WITH selected as (
        SELECT UNNEST(ARRAY [{", ".join([ f"'{td['id']}'" for td in test_definitions ])}]) AS id
    )
    UPDATE {schema}.test_definitions
    SET 
        {update_target_table_column}
        table_groups_id = '{target_table_group}'::UUID,
        test_suite_id = '{target_test_suite}'::UUID
    FROM {schema}.test_definitions td
        INNER JOIN selected ON (td.id = selected.id::UUID)
    WHERE td.id = test_definitions.id;
    """
    db.execute_sql_raw(sql)
    st.cache_data.clear()


def copy(schema, test_definitions, target_table_group, target_test_suite, target_table_column=None):
    if target_table_column is not None:
        update_target_column = f"'{target_table_column['column_name']}' as column_name"
        update_target_table = f"'{target_table_column['table_name']}' as table_name"
    else:
        update_target_column = "td.column_name"
        update_target_table = "td.table_name"
    test_definition_ids = [f"'{td['id']}'" for td in test_definitions]
    sql = f"""
        INSERT INTO {schema}.test_definitions
        (
            profiling_as_of_date,
            last_manual_update,
            skip_errors,
            custom_query,
            test_definition_status,
            export_to_observability,
            column_name,
            watch_level,
            table_groups_id,
            profile_run_id,
            test_type,
            test_suite_id,
            test_description,
            test_action,
            test_mode,
            lock_refresh,
            last_auto_gen_date,
            schema_name,
            table_name,
            test_active,
            severity,
            check_result,
            baseline_ct,
            baseline_unique_ct,
            baseline_value,
            baseline_value_ct,
            threshold_value,
            baseline_sum,
            baseline_avg,
            baseline_sd,
            lower_tolerance,
            upper_tolerance,
            subset_condition,
            groupby_names,
            having_condition,
            window_date_column,
            match_schema_name,
            match_table_name,
            match_column_names,
            match_subset_condition,
            match_groupby_names,
            match_having_condition,
            window_days
        )
        SELECT
            td.profiling_as_of_date,
            td.last_manual_update,
            td.skip_errors,
            td.custom_query,
            td.test_definition_status,
            td.export_to_observability,
            {update_target_column},
            td.watch_level,
            '{target_table_group}'::UUID AS table_groups_id,
            CASE WHEN td.table_groups_id = '{target_table_group}' THEN td.profile_run_id ELSE NULL END AS profile_run_id,
            td.test_type,
            '{target_test_suite}'::UUID AS test_suite_id,
            td.test_description,
            td.test_action,
            td.test_mode,
            td.lock_refresh,
            td.last_auto_gen_date,
            td.schema_name,
            {update_target_table},
            td.test_active,
            td.severity,
            td.check_result,
            td.baseline_ct,
            td.baseline_unique_ct,
            td.baseline_value,
            td.baseline_value_ct,
            td.threshold_value,
            td.baseline_sum,
            td.baseline_avg,
            td.baseline_sd,
            td.lower_tolerance,
            td.upper_tolerance,
            td.subset_condition,
            td.groupby_names,
            td.having_condition,
            td.window_date_column,
            td.match_schema_name,
            td.match_table_name,
            td.match_column_names,
            td.match_subset_condition,
            td.match_groupby_names,
            td.match_having_condition,
            td.window_days
        FROM {schema}.test_definitions as td
        WHERE 
            td.id in ({",".join(test_definition_ids)})
        ;
    """
    db.execute_sql(sql)
    st.cache_data.clear()


def get_test_definitions_collision(schema, test_definitions, target_table_group, target_test_suite):
    test_definition_keys = [f"('{td['table_name']}', '{td['column_name']}', '{td['test_type']}')" for td in test_definitions]
    test_definitions_keys_str = f"({", ".join(test_definition_keys)})"
    sql = f"""
    SELECT table_name, column_name, test_type, lock_refresh
    FROM {schema}.test_definitions
    WHERE table_groups_id = '{target_table_group}'
    AND test_suite_id = '{target_test_suite}'
    AND last_auto_gen_date IS NOT NULL 
    AND (table_name, column_name, test_type) in {test_definitions_keys_str};
    """
    return db.retrieve_data(sql)

