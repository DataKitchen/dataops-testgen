import testgen.ui.services.database_service as db

"""
Shared queries for standard lookups
  - should be called by cached functions within page
"""


def run_project_lookup_query(str_schema):
    str_sql = f"""
        SELECT
            id::VARCHAR(50),
            project_code,
            project_name,
            effective_from_date,
            observability_api_url,
            observability_api_key
        FROM {str_schema}.projects
        ORDER BY project_name
    """
    return db.retrieve_data(str_sql)


def get_project_by_code(schema: str, project_code: str):
    str_sql = f"""
      SELECT
        id::VARCHAR(50),
        project_code,
        project_name,
        effective_from_date,
        observability_api_url,
        observability_api_key
      FROM {schema}.projects
      WHERE project_code = {db.make_value_db_friendly(project_code)};
    """
    results = db.retrieve_data(str_sql)
    if results.size <= 0:
        return None
    return results.iloc[0]


def run_test_type_lookup_query(str_schema, str_test_type=None, boo_show_referential=True, boo_show_table=True,
                               boo_show_column=True, boo_show_custom=True):
    if str_test_type:
        str_criteria = f" AND tt.test_type = '{str_test_type}'"
    else:
        str_criteria = ""

    if (boo_show_referential and boo_show_table and boo_show_column and boo_show_custom) == False:
        str_scopes = ""
        str_scopes += "'referential'," if boo_show_referential else ""
        str_scopes += "'table'," if boo_show_table else ""
        str_scopes += "'column'," if boo_show_column else ""
        str_scopes += "'custom'," if boo_show_custom else ""
        if str_scopes > "":
            str_criteria += f"AND tt.test_scope in ({str_scopes[:-1]})"

    str_sql = f"""
            SELECT tt.id, tt.test_type, tt.id as cat_test_id,
                   tt.test_name_short, tt.test_name_long, tt.test_description,
                   tt.measure_uom, COALESCE(tt.measure_uom_description, '') as measure_uom_description,
                   tt.default_parm_columns, tt.default_severity,
                   tt.run_type, tt.test_scope, tt.dq_dimension, tt.threshold_description,
                   tt.column_name_prompt, tt.column_name_help,
                   tt.default_parm_prompts, tt.default_parm_help, tt.usage_notes,
                   CASE tt.test_scope WHEN 'referential' THEN '⧉ ' WHEN 'custom' THEN '⛭ ' WHEN 'table' THEN '⊞ ' WHEN 'column' THEN '≣ ' ELSE '? ' END
                    || tt.test_name_short || ': ' || lower(tt.test_name_long)
                    || CASE WHEN tt.selection_criteria > '' THEN ' [auto-generated]' ELSE '' END as select_name
              FROM {str_schema}.test_types tt
             WHERE tt.active = 'Y' {str_criteria}
            ORDER BY CASE tt.test_scope WHEN 'referential' THEN 1 WHEN 'custom' THEN 2 WHEN 'table' THEN 3 WHEN 'column' THEN 4 ELSE 5 END,
                     tt.test_name_short;
    """
    return db.retrieve_data(str_sql)


def run_connections_lookup_query(str_schema, str_project_code):
    str_sql = f"""
           SELECT c.id::VARCHAR(50), c.connection_id, c.connection_name
             FROM {str_schema}.connections c
             WHERE c.project_code = '{str_project_code}'
             ORDER BY connection_name
    """
    return db.retrieve_data(str_sql)


def run_table_groups_lookup_query(str_schema, str_project_code, connection_id=None, table_group_id=None):
    str_sql = f"""
           SELECT tg.id::VARCHAR(50), tg.table_groups_name, tg.connection_id, tg.table_group_schema
             FROM {str_schema}.table_groups tg
    """

    if connection_id:
        str_sql += f"""
             inner join {str_schema}.connections c on c.connection_id = tg.connection_id
        """

    str_sql += f"""
                       WHERE tg.project_code = '{str_project_code}'
    """

    if table_group_id:
        str_sql += f"""
                AND tg.id = '{table_group_id}'::UUID
        """

    if connection_id:
        str_sql += f"""
                AND c.id = '{connection_id}'::UUID
        """

    str_sql += """
           ORDER BY table_groups_name
    """
    return db.retrieve_data(str_sql)


def run_table_lookup_query(str_schema, str_table_groups_id):
    str_sql = f"""
           SELECT table_name
             FROM {str_schema}.data_table_chars
            WHERE table_groups_id = '{str_table_groups_id}'::UUID
              AND drop_date IS NULL
           ORDER BY table_name
    """
    return db.retrieve_data(str_sql)


def run_column_lookup_query(str_schema, str_table_groups_id, str_table_name):
    str_sql = f"""
           SELECT column_name
             FROM {str_schema}.data_column_chars
            WHERE table_groups_id = '{str_table_groups_id}'::UUID
              AND table_name = '{str_table_name}'
              AND drop_date IS NULL
           ORDER BY column_name
    """
    return db.retrieve_data(str_sql)


def run_test_suite_lookup_by_tgroup_query(str_schema, str_table_groups_id, test_suite_name=None):
    str_sql = f"""
           SELECT id::VARCHAR(50), test_suite, test_suite_schema, severity, export_to_observability
             FROM {str_schema}.test_suites
            WHERE table_groups_id = '{str_table_groups_id}'
    """

    if test_suite_name:
        str_sql += f"""
               AND test_suite = '{test_suite_name}'
        """

    str_sql += """
           ORDER BY test_suite
    """

    return db.retrieve_data(str_sql)


def run_test_suite_lookup_by_project_query(str_schema, str_project):
    str_sql = f"""
           SELECT s.id::VARCHAR(50), s.test_suite, s.test_suite_schema,
                  s.test_suite
                    || CASE
                         WHEN tg.table_groups_name IS NULL THEN ''
                         ELSE '(' || tg.table_groups_name || ')'
                       END as test_suite_with_tg,
                  s.test_suite_description
             FROM {str_schema}.test_suites s
           LEFT JOIN {str_schema}.table_groups tg
             ON (s.table_groups_id = tg.id)
            WHERE s.project_code = '{str_project}'
           ORDER BY s.test_suite
    """
    return db.retrieve_data(str_sql)


def run_test_run_lookup_by_date(str_schema, str_project_code, str_run_date):
    str_sql = f"""
        SELECT
            r.id::VARCHAR(50),
            r.test_starttime::VARCHAR || ' - ' || s.test_suite as test_run_desc
        FROM {str_schema}.test_runs r
        LEFT JOIN {str_schema}.test_suites s ON  r.test_suite_id = s.id)
        WHERE
            s.project_code = '{str_project_code}'
            AND r.test_starttime::DATE = '{str_run_date}'
        ORDER BY r.test_starttime DESC
    """
    return db.retrieve_data(str_sql)


def update_anomaly_disposition(selected, str_schema, str_new_status):
    def finalize_small_update(status, ids):
        return f"""UPDATE {str_schema}.profile_anomaly_results
                      SET disposition = NULLIF('{status}', 'No Decision')
                    WHERE id IN ({ids});"""

    def finalize_big_update(status, ids):
        return f"""WITH selects
                    as ( SELECT UNNEST(ARRAY [{ids}]) AS selected_id )
                   UPDATE {str_schema}.profile_anomaly_results
                      SET disposition = NULLIF('{status}', 'No Decision')
                     FROM {str_schema}.profile_anomaly_results r
                   INNER JOIN selects s
                      ON (r.id = s.selected_id)
                    WHERE r.id = profile_anomaly_results.id;"""

    lst_ids = [row["id"] for row in selected if "id" in row]
    lst_updates = []
    str_ids = ""

    if len(lst_ids) > 0:
        for my_id in lst_ids:
            str_ids += f" '{my_id}'::UUID,"
        str_ids = str_ids.rstrip(",")
        if len(lst_ids) > 4:
            lst_updates.append(finalize_big_update(str_new_status, str_ids))
        else:
            lst_updates.append(finalize_small_update(str_new_status, str_ids))

        for q in lst_updates:
            db.execute_sql_raw(q)

    return True


def update_result_disposition(selected, str_schema, str_new_status):
    active_yn = "N" if str_new_status == "Inactive" else "Y"

    def finalize_small_update(status, ids):
        return f"""UPDATE {str_schema}.test_results
                      SET disposition = NULLIF('{status}', 'No Decision')
                    WHERE id IN ({ids});"""

    def finalize_big_update(status, ids):
        return f"""WITH selects
                    as ( SELECT UNNEST(ARRAY [{ids}]) AS selected_id )
                   UPDATE {str_schema}.test_results
                      SET disposition = NULLIF('{status}', 'No Decision')
                     FROM {str_schema}.test_results r
                   INNER JOIN selects s
                      ON (r.id = s.selected_id)
                    WHERE r.id = test_results.id;"""

    def finalize_test_update(ids):
        str_lock_test = ", lock_refresh = 'N'" if active_yn == "Y" else ", lock_refresh = 'Y'"
        return f"""WITH selects
                    as ( SELECT UNNEST(ARRAY [{ids}]) AS selected_id )
                   UPDATE {str_schema}.test_definitions
                      SET test_active = '{active_yn}',
                          last_manual_update = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' {str_lock_test}
                     FROM {str_schema}.test_definitions d
                   INNER JOIN {str_schema}.test_results r
                      ON (d.id = r.test_definition_id)
                   INNER JOIN selects s
                      ON (r.id = s.selected_id)
                    WHERE d.id = test_definitions.id"""

    lst_ids = [row["test_result_id"] for row in selected if "test_result_id" in row]
    lst_updates = []
    str_ids = ""

    for my_id in lst_ids:
        str_ids += f" '{my_id}'::UUID,"
    str_ids = str_ids.rstrip(",")

    if len(lst_ids) > 0:
        if len(lst_ids) > 4:
            lst_updates.append(finalize_big_update(str_new_status, str_ids))
        else:
            lst_updates.append(finalize_small_update(str_new_status, str_ids))
        lst_updates.append(finalize_test_update(str_ids))

        for q in lst_updates:
            db.execute_sql_raw(q)

    return True
