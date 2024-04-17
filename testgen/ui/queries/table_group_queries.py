import streamlit as st

import testgen.ui.services.database_service as db


def _get_select_statement(schema):
    return f"""
               SELECT id::VARCHAR(50), project_code, connection_id, table_groups_name,
                      table_group_schema,
                      profiling_include_mask, profiling_exclude_mask,
                      profiling_table_set,
                      profile_id_column_mask, profile_sk_column_mask,
                      profile_use_sampling, profile_sample_percent, profile_sample_min_count,
                      profiling_delay_days
               FROM {schema}.table_groups
               """


@st.cache_data(show_spinner=False)
def get_by_id(schema, table_group_id):
    sql = _get_select_statement(schema)
    sql += f"""WHERE id = '{table_group_id}'
           ORDER BY table_groups_name
    """
    return db.retrieve_data(sql)


@st.cache_data(show_spinner=False)
def get_by_connection(schema, project_code, connection_id):
    sql = _get_select_statement(schema)
    sql += f"""WHERE project_code = '{project_code}'
             AND connection_id = '{connection_id}'
            ORDER BY table_groups_name
     """
    return db.retrieve_data(sql)


def edit(schema, table_group):
    sql = f"""UPDATE {schema}.table_groups
                SET
                    table_groups_name='{table_group["table_groups_name"]}',
                    table_group_schema='{table_group["table_group_schema"]}',
                    profiling_table_set=NULLIF('{table_group["profiling_table_set"]}', ''),
                    profiling_include_mask='{table_group["profiling_include_mask"]}',
                    profiling_exclude_mask='{table_group["profiling_exclude_mask"]}',
                    profile_id_column_mask='{table_group["profile_id_column_mask"]}',
                    profile_sk_column_mask='{table_group["profile_sk_column_mask"]}',
                    profile_use_sampling='{'Y' if table_group["profile_use_sampling"] else 'N'}',
                    profile_sample_percent='{table_group["profile_sample_percent"]}',
                    profile_sample_min_count={int(table_group["profile_sample_min_count"])},
                    profiling_delay_days='{table_group["profiling_delay_days"]}'
                where
                    id = '{table_group["id"]}'
                ;
                    """
    db.execute_sql(sql)
    st.cache_data.clear()


def add(schema, table_group):
    sql = f"""INSERT INTO {schema}.table_groups
        (id,
        project_code,
        connection_id,
        table_groups_name,
        table_group_schema,
        profiling_table_set,
        profiling_include_mask,
        profiling_exclude_mask,
        profile_id_column_mask,
        profile_sk_column_mask,
        profile_use_sampling,
        profile_sample_percent,
        profile_sample_min_count,
        profiling_delay_days)
    SELECT
        gen_random_uuid(),
        '{table_group["project_code"]}',
        '{table_group["connection_id"]}',
        '{table_group["table_groups_name"]}',
        '{table_group["table_group_schema"]}',
        NULLIF('{table_group["profiling_table_set"]}', ''),
        '{table_group["profiling_include_mask"]}',
        '{table_group["profiling_exclude_mask"]}',
        '{table_group["profile_id_column_mask"]}'::character varying(2000),
        '{table_group["profile_sk_column_mask"]}'::character varying,
        '{'Y' if table_group["profile_use_sampling"]=='True' else 'N' }'::character varying,
        '{table_group["profile_sample_percent"]}'::character varying,
        {table_group["profile_sample_min_count"]}, '{table_group["profiling_delay_days"]}'::character varying
        ;"""
    db.execute_sql(sql)
    st.cache_data.clear()


def delete(schema, table_group_ids):
    if table_group_ids is None or len(table_group_ids) == 0:
        raise ValueError("No table group is specified.")

    items = [f"'{item}'" for item in table_group_ids]
    sql = f"""DELETE FROM {schema}.table_groups WHERE id in ({",".join(items)})"""
    db.execute_sql(sql)
    st.cache_data.clear()
