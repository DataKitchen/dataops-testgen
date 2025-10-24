import logging
from datetime import datetime

from testgen.commands.queries.refresh_data_chars_query import ColumnChars, RefreshDataCharsSQL
from testgen.common.database.database_service import (
    execute_db_queries,
    fetch_dict_from_db,
    fetch_from_db_threaded,
    write_to_app_db,
)
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")


def run_data_chars_refresh(connection: Connection, table_group: TableGroup, run_date: datetime) -> list[ColumnChars]:
    sql_generator = RefreshDataCharsSQL(connection, table_group)

    LOG.info("Getting DDF for table group")
    try:
        data_chars = fetch_dict_from_db(*sql_generator.get_schema_ddf(), use_target_db=True)
    except Exception as e:
        raise RuntimeError(f"Error refreshing columns for data catalog. {get_exception_message(e)}") from e
    
    data_chars = [ColumnChars(**column) for column in data_chars]
    if data_chars:
        distinct_tables = {column.table_name for column in data_chars}
        LOG.info(f"Tables: {len(distinct_tables)}, Columns: {len(data_chars)}")
        count_queries = sql_generator.get_row_counts(distinct_tables)
        
        LOG.info("Getting row counts for table group")
        count_results, _, error_data = fetch_from_db_threaded(
            count_queries, use_target_db=True, max_threads=connection.max_threads,
        )

        count_map = dict(count_results)
        for column in data_chars:
            column.record_ct = count_map.get(column.table_name)

        write_data_chars(data_chars, sql_generator, run_date)

        if error_data:
            raise RuntimeError(f"Error refreshing row counts for data catalog. {next(iter(error_data.values()))}")
    else:
        LOG.warning("No tables detected in table group")

    return data_chars


def write_data_chars(data_chars: list[ColumnChars], sql_generator: RefreshDataCharsSQL, run_date: datetime) -> None:
    staging_results = sql_generator.get_staging_data_chars(data_chars, run_date)

    LOG.info("Writing data characteristics to staging")
    write_to_app_db(staging_results, sql_generator.staging_columns, sql_generator.staging_table)

    LOG.info("Refreshing data characteristics and deleting staging")
    execute_db_queries(sql_generator.update_data_chars(run_date))
