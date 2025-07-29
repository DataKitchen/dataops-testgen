import logging

from progress.spinner import Spinner

from testgen.commands.queries.refresh_data_chars_query import CRefreshDataCharsSQL
from testgen.common.database.database_service import (
    execute_db_queries,
    fetch_dict_from_db,
    fetch_from_db_threaded,
    write_to_app_db,
)
from testgen.common.get_pipeline_parms import TestExecutionParams

LOG = logging.getLogger("testgen")
STAGING_TABLE = "stg_data_chars_updates"


def run_refresh_data_chars_queries(params: TestExecutionParams, run_date: str, spinner: Spinner=None):
    LOG.info("CurrentStep: Initializing Data Characteristics Refresh")
    sql_generator = CRefreshDataCharsSQL(params, run_date, STAGING_TABLE)

    LOG.info("CurrentStep: Getting DDF for table group")
    ddf_results = fetch_dict_from_db(*sql_generator.GetDDFQuery(), use_target_db=True)

    distinct_tables = {
        f"{item['table_schema']}.{item['table_name']}"
        for item in ddf_results
    }
    if distinct_tables:
        count_queries = sql_generator.GetRecordCountQueries(distinct_tables)
        
        LOG.info("CurrentStep: Getting record counts for table group")
        count_results, _, error_count = fetch_from_db_threaded(
            count_queries, use_target_db=True, max_threads=params["max_threads"], spinner=spinner
        )
        if error_count:
            LOG.warning(f"{error_count} errors were encountered while retrieving record counts.")
    else:
        count_results = []
        LOG.warning("No tables detected in table group. Skipping retrieval of record counts")

    count_map = dict(count_results)
    staging_columns = [
        "project_code",
        "table_groups_id",
        "run_date",
        "schema_name",
        "table_name",
        "column_name",
        "position",
        "general_type",
        "column_type",
        "record_ct",
    ]
    staging_records = [
        [
            item["project_code"],
            params["table_groups_id"],
            run_date,
            item["table_schema"],
            item["table_name"],
            item["column_name"],
            item["ordinal_position"],
            item["general_type"],
            item["data_type"],
            count_map.get(f"{item['table_schema']}.{item['table_name']}", 0),
        ]
        for item in ddf_results
    ]

    LOG.info("CurrentStep: Writing data characteristics to staging")
    write_to_app_db(staging_records, staging_columns, STAGING_TABLE)

    LOG.info("CurrentStep: Refreshing data characteristics and deleting staging")
    execute_db_queries([
        sql_generator.GetDataCharsUpdateQuery(),
        sql_generator.GetStagingDeleteQuery(),
    ])
