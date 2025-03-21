import streamlit as st

from testgen.common.read_file import replace_templated_functions
from testgen.ui.services import database_service as db


def get_source_data(hi_data):
    str_schema = st.session_state["dbschema"]
    # Define the query
    str_sql = f"""
            SELECT t.lookup_query, tg.table_group_schema,
                   c.sql_flavor, c.project_host, c.project_port, c.project_db, c.project_user, c.project_pw_encrypted,
                   c.url, c.connect_by_url, c.connect_by_key, c.private_key, c.private_key_passphrase, c.http_path
              FROM {str_schema}.target_data_lookups t
            INNER JOIN {str_schema}.table_groups tg
               ON ('{hi_data["table_groups_id"]}'::UUID = tg.id)
            INNER JOIN {str_schema}.connections c
               ON (tg.connection_id = c.connection_id)
                AND (t.sql_flavor = c.sql_flavor)
             WHERE t.error_type = 'Profile Anomaly'
               AND t.test_id = '{hi_data["anomaly_id"]}'
               AND t.lookup_query > '';
    """

    def get_lookup_query(test_id, detail_exp, column_names, sql_flavor):
        if test_id in {"1019", "1020"}:
            start_index = detail_exp.find("Columns: ")
            if start_index == -1:
                columns = [col.strip() for col in column_names.split(",")]
            else:
                start_index += len("Columns: ")
                column_names_str = detail_exp[start_index:]
                columns = [col.strip() for col in column_names_str.split(",")]
            quote = "`" if sql_flavor == "databricks" else '"'
            queries = [
                f"SELECT '{column}' AS column_name, MAX({quote}{column}{quote}) AS max_date_available FROM {{TARGET_SCHEMA}}.{{TABLE_NAME}}"
                for column in columns
            ]
            sql_query = " UNION ALL ".join(queries) + " ORDER BY max_date_available DESC;"
        else:
            sql_query = ""
        return sql_query

    def replace_parms(str_query):
        str_query = (
            get_lookup_query(hi_data["anomaly_id"], hi_data["detail"], hi_data["column_name"], lst_query[0]["sql_flavor"])
            if lst_query[0]["lookup_query"] == "created_in_ui"
            else lst_query[0]["lookup_query"]
        )
        str_query = str_query.replace("{TARGET_SCHEMA}", lst_query[0]["table_group_schema"])
        str_query = str_query.replace("{TABLE_NAME}", hi_data["table_name"])
        str_query = str_query.replace("{COLUMN_NAME}", hi_data["column_name"])
        str_query = str_query.replace("{DETAIL_EXPRESSION}", hi_data["detail"])
        str_query = str_query.replace("{PROFILE_RUN_DATE}", hi_data["profiling_starttime"])
        str_query = replace_templated_functions(str_query, lst_query[0]["sql_flavor"])

        if str_query is None or str_query == "":
            raise ValueError("Lookup query is not defined for this Anomaly Type.")
        return str_query

    try:
        # Retrieve SQL for customer lookup
        lst_query = db.retrieve_data_list(str_sql)

        # Retrieve and return data as df
        if lst_query:
            str_sql = replace_parms(str_sql)
            df = db.retrieve_target_db_df(
                lst_query[0]["sql_flavor"],
                lst_query[0]["project_host"],
                lst_query[0]["project_port"],
                lst_query[0]["project_db"],
                lst_query[0]["project_user"],
                lst_query[0]["project_pw_encrypted"],
                str_sql,
                lst_query[0]["url"],
                lst_query[0]["connect_by_url"],
                lst_query[0]["connect_by_key"],
                lst_query[0]["private_key"],
                lst_query[0]["private_key_passphrase"],
                lst_query[0]["http_path"],
            )
            if df.empty:
                return "ND", "Data that violates Hygiene Issue criteria is not present in the current dataset.", str_sql, None
            else:
                return "OK", None, str_sql, df
        else:
            return "NA", "Source data lookup is not available for this Issue.", None, None

    except Exception as e:
        return "ERR", f"Source data lookup query caused an error:\n\n{e.args[0]}", None, None
