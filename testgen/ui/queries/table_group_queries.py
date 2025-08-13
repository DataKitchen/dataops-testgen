from typing import TypedDict

from sqlalchemy.engine import Row

from testgen.commands.queries.profiling_query import CProfilingSQL
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.ui.services.database_service import fetch_from_target_db


class TableGroupPreview(TypedDict):
    schema: str
    tables: dict[str, bool]
    column_count: int
    success: bool
    message: str | None


def get_table_group_preview(
    table_group: TableGroup,
    connection: Connection | None = None,
    verify_table_access: bool = False,
) -> TableGroupPreview:
    table_group_preview: TableGroupPreview = {
        "schema": table_group.table_group_schema,
        "tables": {},
        "column_count": 0,
        "success": True,
        "message": None,
    }
    if connection or table_group.connection_id:
        try:
            connection = connection or Connection.get(table_group.connection_id)

            table_group_results = _fetch_table_group_columns(connection, table_group)

            for column in table_group_results:
                table_group_preview["schema"] = column["table_schema"]
                table_group_preview["tables"][column["table_name"]] = None
                table_group_preview["column_count"] += 1

            if len(table_group_results) <= 0:
                table_group_preview["success"] = False
                table_group_preview["message"] = (
                    "No tables found matching the criteria. Please check the Table Group configuration"
                    " or the database permissions."
                )

            if verify_table_access:
                for table_name in table_group_preview["tables"].keys():
                    try:
                        results = fetch_from_target_db(
                            connection, 
                            (
                                f"SELECT 1 FROM {table_group_preview['schema']}.{table_name} LIMIT 1"
                                if connection.sql_flavor != "mssql"
                                else f"SELECT TOP 1 * FROM {table_group_preview['schema']}.{table_name}"
                            ),
                        )
                    except Exception as error:
                        table_group_preview["tables"][table_name] = False
                    else:
                        table_group_preview["tables"][table_name] = results is not None and len(results) > 0

                    if not all(table_group_preview["tables"].values()):
                        table_group_preview["message"] = (
                            "Some tables were not accessible. Please the check the database permissions."
                        )
        except Exception as error:
            table_group_preview["success"] = False
            table_group_preview["message"] = error.args[0]
    else:
        table_group_preview["success"] = False
        table_group_preview["message"] = "No connection selected. Please select a connection to preview the Table Group."
    return table_group_preview


def _fetch_table_group_columns(connection: Connection, table_group: TableGroup) -> list[Row]:
    profiling_table_set = table_group.profiling_table_set

    sql_generator = CProfilingSQL(table_group.project_code, connection.sql_flavor)

    sql_generator.table_groups_id = table_group.id
    sql_generator.connection_id = str(table_group.connection_id)
    sql_generator.profile_run_id = ""
    sql_generator.data_schema = table_group.table_group_schema
    sql_generator.parm_table_set = (
        ",".join([f"'{item.strip()}'" for item in profiling_table_set.split(",")])
        if profiling_table_set
        else profiling_table_set
    )
    sql_generator.parm_table_include_mask = table_group.profiling_include_mask
    sql_generator.parm_table_exclude_mask = table_group.profiling_exclude_mask
    sql_generator.profile_id_column_mask = table_group.profile_id_column_mask
    sql_generator.profile_sk_column_mask = table_group.profile_sk_column_mask
    sql_generator.profile_use_sampling = "Y" if table_group.profile_use_sampling else "N"
    sql_generator.profile_sample_percent = table_group.profile_sample_percent
    sql_generator.profile_sample_min_count = table_group.profile_sample_min_count

    return fetch_from_target_db(connection, *sql_generator.GetDDFQuery())
