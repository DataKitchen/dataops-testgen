import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db


@st.cache_data(show_spinner=False)
def get_by_project(schema, project_code, table_group_id=None):
    sql = f"""
            WITH last_gen_date AS (
                SELECT test_suite_id,
                    MAX(last_auto_gen_date) as auto_gen_date
                FROM {schema}.test_definitions
                GROUP BY test_suite_id
            ),
            last_run_date AS (
                SELECT test_suite_id,
                    MAX(test_starttime) as test_starttime
                FROM {schema}.test_runs
                GROUP BY test_suite_id
            ),
            last_run AS (
                SELECT test_runs.test_suite_id,
                    test_runs.id,
                    test_runs.test_starttime,
                    test_runs.test_ct,
                    SUM(
                        CASE
                            WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                            AND test_results.result_status = 'Passed' THEN 1
                            ELSE 0
                        END
                    ) as passed_ct,
                    SUM(
                        CASE
                            WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                            AND test_results.result_status = 'Warning' THEN 1
                            ELSE 0
                        END
                    ) as warning_ct,
                    SUM(
                        CASE
                            WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                            AND test_results.result_status = 'Failed' THEN 1
                            ELSE 0
                        END
                    ) as failed_ct,
                    SUM(
                        CASE
                            WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                            AND test_results.result_status = 'Error' THEN 1
                            ELSE 0
                        END
                    ) as error_ct,
                    SUM(
                        CASE
                            WHEN COALESCE(test_results.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                            ELSE 0
                        END
                    ) as dismissed_ct
                FROM last_run_date lrd
                    LEFT JOIN {schema}.test_runs ON (
                        lrd.test_suite_id = test_runs.test_suite_id
                        AND lrd.test_starttime = test_runs.test_starttime
                    )
                    LEFT JOIN {schema}.test_results ON (
                        test_runs.id = test_results.test_run_id
                    )
                GROUP BY test_runs.id
            )
            SELECT
                suites.id::VARCHAR(50),
                suites.project_code,
                suites.test_suite,
                suites.connection_id::VARCHAR(50),
                connections.connection_name,
                suites.table_groups_id::VARCHAR(50),
                groups.table_groups_name,
                suites.test_suite_description,
                suites.test_action,
                CASE WHEN suites.severity IS NULL THEN 'Inherit' ELSE suites.severity END,
                suites.export_to_observability,
                suites.test_suite_schema,
                suites.component_key,
                suites.component_type,
                suites.component_name,
                last_gen_date.auto_gen_date as latest_auto_gen_date,
                last_run.id as latest_run_id, 
                last_run.test_starttime as latest_run_start, 
                last_run.test_ct as last_run_test_ct,
                last_run.passed_ct as last_run_passed_ct, 
                last_run.warning_ct as last_run_warning_ct, 
                last_run.failed_ct as last_run_failed_ct, 
                last_run.error_ct as last_run_error_ct,
                last_run.dismissed_ct as last_run_dismissed_ct
            FROM {schema}.test_suites as suites
            LEFT JOIN last_gen_date
                ON (suites.id = last_gen_date.test_suite_id)
            LEFT JOIN last_run
                ON (suites.id = last_run.test_suite_id)
            LEFT JOIN {schema}.connections AS connections 
                ON (connections.connection_id = suites.connection_id) 
            LEFT JOIN {schema}.table_groups as groups 
                ON (groups.id = suites.table_groups_id) 
            WHERE suites.project_code = '{project_code}'
            """
    
    if table_group_id:
        sql += f"""
               AND suites.table_groups_id = '{table_group_id}'
               """

    sql += """
            ORDER BY suites.test_suite;
    """
    
    return db.retrieve_data(sql)


@st.cache_data(show_spinner=False)
def get_by_id(schema: str, test_suite_id: str) -> pd.DataFrame:
    sql = f"""
            SELECT
                suites.id::VARCHAR(50),
                suites.project_code,
                suites.test_suite,
                suites.connection_id::VARCHAR(50),
                suites.table_groups_id::VARCHAR(50),
                suites.test_suite_description,
                suites.test_action,
                CASE WHEN suites.severity IS NULL THEN 'Inherit' ELSE suites.severity END,
                suites.export_to_observability,
                suites.test_suite_schema,
                suites.component_key,
                suites.component_type,
                suites.component_name
            FROM {schema}.test_suites as suites
            WHERE suites.id = '{test_suite_id}';
        """
    return db.retrieve_data(sql)


def edit(schema, test_suite):
    sql = f"""UPDATE {schema}.test_suites
                SET
                    test_suite='{test_suite["test_suite"]}',
                    test_suite_description='{test_suite["test_suite_description"]}',
                    test_action=NULLIF('{test_suite["test_action"]}', ''),
                    severity=NULLIF('{test_suite["severity"]}', 'Inherit'),
                    export_to_observability='{'Y' if test_suite["export_to_observability"] else 'N'}',
                    test_suite_schema=NULLIF('{test_suite["test_suite_schema"]}', ''),
                    component_key=NULLIF('{test_suite["component_key"]}', ''),
                    component_type=NULLIF('{test_suite["component_type"]}', ''),
                    component_name=NULLIF('{test_suite["component_name"]}', '')
                where
                    id = '{test_suite["id"]}';
                    """
    db.execute_sql(sql)
    st.cache_data.clear()


def add(schema, test_suite):
    sql = f"""INSERT INTO {schema}.test_suites
                (id,
                project_code, test_suite, connection_id, table_groups_id, test_suite_description, test_action,
                severity, export_to_observability, test_suite_schema, component_key, component_type,
                component_name)
            SELECT
                gen_random_uuid(),
                '{test_suite["project_code"]}',
                '{test_suite["test_suite"]}',
                '{test_suite["connection_id"]}',
                '{test_suite["table_groups_id"]}',
                NULLIF('{test_suite["test_suite_description"]}', ''),
                NULLIF('{test_suite["test_action"]}', ''),
                NULLIF('{test_suite["severity"]}', 'Inherit'),
                '{'Y' if test_suite["export_to_observability"] else 'N' }'::character varying,
                NULLIF('{test_suite["test_suite_schema"]}', ''),
                NULLIF('{test_suite["component_key"]}', ''),
                NULLIF('{test_suite["component_type"]}', ''),
                NULLIF('{test_suite["component_name"]}', '')
                ;"""
    db.execute_sql(sql)
    st.cache_data.clear()


def delete(schema, test_suite_ids: list[str]):
    if not test_suite_ids:
        raise ValueError("No table group is specified.")

    ids_str = ",".join([f"'{item}'" for item in test_suite_ids])
    sql = f"""DELETE FROM {schema}.test_suites WHERE id in ({ids_str})"""
    db.execute_sql(sql)
    st.cache_data.clear()


def get_test_suite_dependencies(schema: str, test_suite_ids: list[str]) -> pd.DataFrame:
    ids_str = ", ".join([f"'{item}'" for item in test_suite_ids])
    sql = f"""
        SELECT DISTINCT test_suite_id FROM {schema}.test_definitions WHERE test_suite_id in ({ids_str})
        UNION
        SELECT DISTINCT test_suite_id FROM {schema}.test_results WHERE test_suite_id in ({ids_str});
    """
    return db.retrieve_data(sql)


def get_test_suite_usage(schema: str, test_suite_ids: list[str]) -> pd.DataFrame:
    ids_str = ", ".join([f"'{item}'" for item in test_suite_ids])
    sql = f"""
        SELECT DISTINCT test_suite_id FROM {schema}.test_runs WHERE test_suite_id in ({ids_str}) AND status = 'Running'
    """
    return db.retrieve_data(sql)


def get_test_suite_refresh_check(schema, test_suite_id):
    sql = f"""
           SELECT COUNT(*) as test_ct,
                  SUM(CASE WHEN COALESCE(d.lock_refresh, 'N') = 'N' THEN 1 ELSE 0 END) as unlocked_test_ct,
                  SUM(CASE WHEN COALESCE(d.lock_refresh, 'N') = 'N' AND d.last_manual_update IS NOT NULL THEN 1 ELSE 0 END) as unlocked_edits_ct
             FROM {schema}.test_definitions d
           INNER JOIN {schema}.test_types t
              ON (d.test_type = t.test_type)
            WHERE d.test_suite_id = '{test_suite_id}'
              AND t.run_type = 'CAT'
              AND t.selection_criteria IS NOT NULL;
"""
    return db.retrieve_data_list(sql)[0]


def get_generation_sets(schema):
    sql = f"""
           SELECT DISTINCT generation_set
             FROM {schema}.generation_sets
           ORDER BY generation_set;
"""
    return db.retrieve_data(sql)


def lock_edited_tests(schema, test_suite_id):
    sql = f"""
           UPDATE {schema}.test_definitions
              SET lock_refresh = 'Y'
            WHERE test_suite_id = '{test_suite_id}'
              AND last_manual_update IS NOT NULL
              AND lock_refresh = 'N';
"""
    db.execute_sql(sql)
    return True
