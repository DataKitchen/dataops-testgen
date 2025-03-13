import uuid

import streamlit as st

import testgen.ui.services.database_service as db


def _get_select_statement(schema):
    return f"""
               SELECT id::VARCHAR(50), project_code, connection_id, table_groups_name,
                      table_group_schema,
                      profiling_include_mask, profiling_exclude_mask,
                      profiling_table_set,
                      profile_id_column_mask, profile_sk_column_mask,
                      description, data_source, source_system, source_process, data_location,
                      business_domain, stakeholder_group, transform_level, data_product,
                      profile_use_sampling, profile_sample_percent, profile_sample_min_count,
                      profiling_delay_days, profile_flag_cdes
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
def get_by_name(project_code: str, table_group_name: str) -> dict | None:
    schema: str = st.session_state["dbschema"]
    sql = _get_select_statement(schema)
    sql += f"""WHERE project_code = '{project_code}' AND table_groups_name = '{table_group_name}';"""
    results = db.retrieve_data(sql)
    if results.empty:
        return None
    return results.iloc[0].to_dict()


def get_test_suite_ids_by_table_group_names(schema, table_group_names):
    names_str = ", ".join([f"'{item}'" for item in table_group_names])
    sql = f"""
        SELECT ts.id::VARCHAR
        FROM {schema}.test_suites ts
        INNER JOIN {schema}.table_groups tg ON tg.id = ts.table_groups_id
        WHERE tg.table_groups_name in ({names_str})
    """
    return db.retrieve_data(sql)



def get_table_group_dependencies(schema, table_group_names):
    if table_group_names is None or len(table_group_names) == 0:
        raise ValueError("No Table Group is specified.")

    table_group_items = [f"'{item}'" for item in table_group_names]
    sql = f"""select ppr.profile_run_id from {schema}.profile_pair_rules ppr
    INNER JOIN {schema}.profiling_runs pr ON pr.id = ppr.profile_run_id
    INNER JOIN {schema}.table_groups tg ON tg.id = pr.table_groups_id
    where tg.table_groups_name in ({",".join(table_group_items)})
    union
    select par.table_groups_id from {schema}.profile_anomaly_results par INNER JOIN {schema}.table_groups tg ON tg.id = par.table_groups_id where tg.table_groups_name in ({",".join(table_group_items)})
    union
    select pr.table_groups_id from {schema}.profile_results pr INNER JOIN {schema}.table_groups tg ON tg.id = pr.table_groups_id where tg.table_groups_name in ({",".join(table_group_items)})
    union
    select pr.table_groups_id from {schema}.profiling_runs pr INNER JOIN {schema}.table_groups tg ON tg.id = pr.table_groups_id where tg.table_groups_name in ({",".join(table_group_items)})
    union
    select dtc.table_groups_id from {schema}.data_table_chars dtc INNER JOIN {schema}.table_groups tg ON tg.id = dtc.table_groups_id where tg.table_groups_name in ({",".join(table_group_items)})
    union
    select dcs.table_groups_id from {schema}.data_column_chars dcs INNER JOIN {schema}.table_groups tg ON tg.id = dcs.table_groups_id where tg.table_groups_name in ({",".join(table_group_items)});"""
    return db.retrieve_data(sql)


def get_table_group_usage(schema, table_group_names):
    items = [f"'{item}'" for item in table_group_names]
    sql = f"""select distinct pr.id from {schema}.profiling_runs pr
INNER JOIN {schema}.table_groups tg ON tg.id = pr.table_groups_id
where tg.table_groups_name in ({",".join(items)}) and pr.status = 'Running'"""
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
                    profiling_delay_days='{table_group["profiling_delay_days"]}',
                    profile_flag_cdes={table_group["profile_flag_cdes"]},
                    description='{table_group["description"]}',
                    data_source=NULLIF('{table_group["data_source"]}', ''),
                    source_system=NULLIF('{table_group["source_system"]}', ''),
                    source_process=NULLIF('{table_group["source_process"]}', ''),
                    data_location=NULLIF('{table_group["data_location"]}', ''),
                    business_domain=NULLIF('{table_group["business_domain"]}', ''),
                    stakeholder_group=NULLIF('{table_group["stakeholder_group"]}', ''),
                    transform_level=NULLIF('{table_group["transform_level"]}', ''),
                    data_product=NULLIF('{table_group["data_product"]}', '')
                WHERE
                    id = '{table_group["id"]}'
                ;
                    """
    db.execute_sql(sql)
    st.cache_data.clear()


def add(schema, table_group) -> str:
    new_table_group_id = str(uuid.uuid4())
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
        profiling_delay_days,
        profile_flag_cdes,
        description,
        data_source,
        source_system,
        source_process,
        data_location,
        business_domain,
        stakeholder_group,
        transform_level,
        data_product)
    SELECT
        '{new_table_group_id}',
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
        {table_group["profile_sample_min_count"]},
        '{table_group["profiling_delay_days"]}'::character varying,
        {table_group["profile_flag_cdes"]},
        '{table_group["description"]}',
        NULLIF('{table_group["data_source"]}', ''),
        NULLIF('{table_group["source_system"]}', ''),
        NULLIF('{table_group["source_process"]}', ''),
        NULLIF('{table_group["data_location"]}', ''),
        NULLIF('{table_group["business_domain"]}', ''),
        NULLIF('{table_group["stakeholder_group"]}', ''),
        NULLIF('{table_group["transform_level"]}', ''),
        NULLIF('{table_group["data_product"]}', '')
        ;"""
    db.execute_sql(sql)
    st.cache_data.clear()
    return new_table_group_id


def delete(schema, table_group_ids):
    if table_group_ids is None or len(table_group_ids) == 0:
        raise ValueError("No table group is specified.")

    items = [f"'{item}'" for item in table_group_ids]
    sql = f"""DELETE FROM {schema}.table_groups WHERE id in ({",".join(items)})"""
    db.execute_sql(sql)
    st.cache_data.clear()


def cascade_delete(schema, table_group_names):
    if table_group_names is None or len(table_group_names) == 0:
        raise ValueError("No Table Group is specified.")

    table_group_items = [f"'{item}'" for item in table_group_names]
    sql = f"""delete from {schema}.profile_pair_rules ppr
USING {schema}.profiling_runs pr, {schema}.table_groups tg
WHERE
pr.id = ppr.profile_run_id
AND tg.id = pr.table_groups_id
AND tg.table_groups_name in ({",".join(table_group_items)});
delete from {schema}.profile_anomaly_results par USING {schema}.table_groups tg where tg.id = par.table_groups_id and tg.table_groups_name in ({",".join(table_group_items)});
delete from {schema}.profile_results pr USING {schema}.table_groups tg where tg.id = pr.table_groups_id and tg.table_groups_name in ({",".join(table_group_items)});
delete from {schema}.profiling_runs pr USING {schema}.table_groups tg where tg.id = pr.table_groups_id and tg.table_groups_name in ({",".join(table_group_items)});
delete from {schema}.data_table_chars dtc USING {schema}.table_groups tg where tg.id = dtc.table_groups_id and tg.table_groups_name in ({",".join(table_group_items)});
delete from {schema}.data_column_chars dcs USING {schema}.table_groups tg where tg.id = dcs.table_groups_id and tg.table_groups_name in ({",".join(table_group_items)});
delete from {schema}.table_groups where table_groups_name in ({",".join(table_group_items)});"""
    db.execute_sql(sql)
    st.cache_data.clear()
