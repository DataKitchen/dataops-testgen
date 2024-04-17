import streamlit as st

import testgen.ui.services.database_service as db


@st.cache_data(show_spinner=False)
def get_by_table_group(schema, project_code, table_group_id):
    sql = f"""
            SELECT
                id::VARCHAR(50),
                project_code, test_suite,
                connection_id::VARCHAR(50),
                table_groups_id::VARCHAR(50),
                test_suite_description, test_action,
                case when severity is null then 'Inherit' else severity end,
                export_to_observability, test_suite_schema, component_key, component_type, component_name
            FROM {schema}.test_suites
            WHERE project_code = '{project_code}'
            AND table_groups_id = '{table_group_id}'
            ORDER BY test_suite;
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


def delete(schema, test_suite_ids):
    if test_suite_ids is None or len(test_suite_ids) == 0:
        raise ValueError("No table group is specified.")

    items = [f"'{item}'" for item in test_suite_ids]
    sql = f"""DELETE FROM {schema}.test_suites WHERE id in ({",".join(items)})"""
    db.execute_sql(sql)
    st.cache_data.clear()


def get_test_suite_usage(schema, test_suite_names):
    test_suite_names_join = [f"'{item}'" for item in test_suite_names]
    sql = f"""
            select distinct test_suite from {schema}.test_definitions where test_suite in ({",".join(test_suite_names_join)})
            union
            select distinct test_suite from {schema}.execution_queue where test_suite in ({",".join(test_suite_names_join)})
            union
            select distinct test_suite from {schema}.test_results where test_suite in ({",".join(test_suite_names_join)});
    """
    return db.retrieve_data(sql)
