import pandas as pd

from testgen.common import ConcatColumnList
from testgen.common.read_file import replace_templated_functions
from testgen.ui.services import database_service as db
from testgen.ui.services.string_service import empty_if_null
from testgen.ui.services.test_definition_service import get_test_definition


def get_test_result_history(db_schema, tr_data):
    if tr_data["auto_gen"]:
        str_where = f"""
            WHERE test_suite_id = '{tr_data["test_suite_id"]}'
              AND table_name = '{tr_data["table_name"]}'
              AND column_names = '{tr_data["column_names"]}'
              AND test_type = '{tr_data["test_type"]}'
              AND auto_gen = TRUE
        """
    else:
        str_where = f"""
            WHERE test_definition_id_runtime = '{tr_data["test_definition_id_runtime"]}'
        """

    str_sql = f"""
           SELECT test_date, test_type,
                  test_name_short, test_name_long, measure_uom, test_operator,
                  threshold_value::NUMERIC, result_measure, result_status
             FROM {db_schema}.v_test_results {str_where}
           ORDER BY test_date DESC;
    """

    df = db.retrieve_data(str_sql)
    # Clean Up
    df["test_date"] = pd.to_datetime(df["test_date"])

    return df


def do_source_data_lookup_custom(db_schema, tr_data):
    # Define the query
    str_sql = f"""
            SELECT d.custom_query as lookup_query, tg.table_group_schema,
                   c.sql_flavor, c.project_host, c.project_port, c.project_db, c.project_user, c.project_pw_encrypted,
                   c.url, c.connect_by_url, c.connect_by_key, c.private_key, c.private_key_passphrase
              FROM {db_schema}.test_definitions d
            INNER JOIN {db_schema}.table_groups tg
               ON ('{tr_data["table_groups_id"]}'::UUID = tg.id)
            INNER JOIN {db_schema}.connections c
               ON (tg.connection_id = c.connection_id)
             WHERE d.id = '{tr_data["test_definition_id_current"]}';
    """

    try:
        # Retrieve SQL for customer lookup
        lst_query = db.retrieve_data_list(str_sql)

        # Retrieve and return data as df
        if lst_query:
            str_sql = lst_query[0]["lookup_query"]
            str_sql = str_sql.replace("{DATA_SCHEMA}", empty_if_null(lst_query[0]["table_group_schema"]))
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
            )
            if df.empty:
                return "ND", "Data that violates Test criteria is not present in the current dataset.", str_sql, None
            else:
                return "OK", None, str_sql, df
        else:
            return "NA", "Source data lookup is not available for this test.", None, None

    except Exception as e:
        return "ERR", f"Source data lookup query caused an error:\n\n{e.args[0]}", str_sql, None


def do_source_data_lookup(db_schema, tr_data, sql_only=False):
    # Define the query
    str_sql = f"""
            SELECT t.lookup_query, tg.table_group_schema,
                   c.sql_flavor, c.project_host, c.project_port, c.project_db, c.project_user, c.project_pw_encrypted,
                   c.url, c.connect_by_url,
                   c.connect_by_key, c.private_key, c.private_key_passphrase
              FROM {db_schema}.target_data_lookups t
            INNER JOIN {db_schema}.table_groups tg
               ON ('{tr_data["table_groups_id"]}'::UUID = tg.id)
            INNER JOIN {db_schema}.connections c
               ON (tg.connection_id = c.connection_id)
               AND (t.sql_flavor = c.sql_flavor)
             WHERE t.error_type = 'Test Results'
               AND t.test_id = '{tr_data["test_type_id"]}'
               AND t.lookup_query > '';
    """

    def replace_parms(df_test, str_query):
        if df_test.empty:
            raise ValueError("This test definition is no longer present.")
        str_query = str_query.replace("{TARGET_SCHEMA}", empty_if_null(lst_query[0]["table_group_schema"]))
        str_query = str_query.replace("{TABLE_NAME}", empty_if_null(tr_data["table_name"]))
        str_query = str_query.replace("{COLUMN_NAME}", empty_if_null(tr_data["column_names"]))
        str_query = str_query.replace("{TEST_DATE}", str(empty_if_null(tr_data["test_date"])))

        str_query = str_query.replace("{CUSTOM_QUERY}", empty_if_null(df_test.at[0, "custom_query"]))
        str_query = str_query.replace("{BASELINE_VALUE}", empty_if_null(df_test.at[0, "baseline_value"]))
        str_query = str_query.replace("{BASELINE_CT}", empty_if_null(df_test.at[0, "baseline_ct"]))
        str_query = str_query.replace("{BASELINE_AVG}", empty_if_null(df_test.at[0, "baseline_avg"]))
        str_query = str_query.replace("{BASELINE_SD}", empty_if_null(df_test.at[0, "baseline_sd"]))
        str_query = str_query.replace("{THRESHOLD_VALUE}", empty_if_null(df_test.at[0, "threshold_value"]))

        str_substitute = empty_if_null(df_test.at[0, "subset_condition"])
        str_substitute = "1=1" if str_substitute == "" else str_substitute
        str_query = str_query.replace("{SUBSET_CONDITION}", str_substitute)

        str_query = str_query.replace("{GROUPBY_NAMES}", empty_if_null(df_test.at[0, "groupby_names"]))
        str_query = str_query.replace("{HAVING_CONDITION}", empty_if_null(df_test.at[0, "having_condition"]))
        str_query = str_query.replace("{MATCH_SCHEMA_NAME}", empty_if_null(df_test.at[0, "match_schema_name"]))
        str_query = str_query.replace("{MATCH_TABLE_NAME}", empty_if_null(df_test.at[0, "match_table_name"]))
        str_query = str_query.replace("{MATCH_COLUMN_NAMES}", empty_if_null(df_test.at[0, "match_column_names"]))

        str_substitute = empty_if_null(df_test.at[0, "match_subset_condition"])
        str_substitute = "1=1" if str_substitute == "" else str_substitute
        str_query = str_query.replace("{MATCH_SUBSET_CONDITION}", str_substitute)

        str_query = str_query.replace("{MATCH_GROUPBY_NAMES}", empty_if_null(df_test.at[0, "match_groupby_names"]))
        str_query = str_query.replace("{MATCH_HAVING_CONDITION}", empty_if_null(df_test.at[0, "match_having_condition"]))
        str_query = str_query.replace("{COLUMN_NAME_NO_QUOTES}", empty_if_null(tr_data["column_names"]))

        str_query = str_query.replace("{WINDOW_DATE_COLUMN}", empty_if_null(df_test.at[0, "window_date_column"]))
        str_query = str_query.replace("{WINDOW_DAYS}", empty_if_null(df_test.at[0, "window_days"]))

        str_substitute = ConcatColumnList(tr_data["column_names"], "<NULL>")
        str_query = str_query.replace("{CONCAT_COLUMNS}", str_substitute)
        str_substitute = ConcatColumnList(df_test.at[0, "match_groupby_names"], "<NULL>")
        str_query = str_query.replace("{CONCAT_MATCH_GROUPBY}", str_substitute)

        if "{{DKFN_" in str_query:
            str_query = replace_templated_functions(str_query, lst_query[0]["sql_flavor"])

        if str_query is None or str_query == "":
            raise ValueError("Lookup query is not defined for this Test Type.")
        return str_query

    try:
        # Retrieve SQL for customer lookup
        lst_query = db.retrieve_data_list(str_sql)

        if sql_only:
            return lst_query, replace_parms, None

        # Retrieve and return data as df
        if lst_query:
            df_test = get_test_definition(db_schema, tr_data["test_definition_id_current"])

            str_sql = replace_parms(df_test, lst_query[0]["lookup_query"])
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
            )
            if df.empty:
                return "ND", "Data that violates Test criteria is not present in the current dataset.", str_sql, None
            else:
                return "OK", None, str_sql, df
        else:
            return "NA", "A source data lookup for this Test is not available.", None, None

    except Exception as e:
        return "ERR", f"Source data lookup query caused:\n\n{e.args[0]}", str_sql, None
