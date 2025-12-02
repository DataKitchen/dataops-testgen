from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID

import streamlit as st

from testgen.commands.queries.refresh_data_chars_query import ColumnChars, RefreshDataCharsSQL
from testgen.commands.run_refresh_data_chars import write_data_chars
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.ui.services.database_service import fetch_from_target_db


class StatsPreview(TypedDict):
    id: UUID
    table_groups_name: str
    table_group_schema: str
    table_ct: int | None
    column_ct: int | None
    approx_record_ct: int | None
    approx_data_point_ct: int | None

class TablePreview(TypedDict):
    column_ct: int
    approx_record_ct: int | None
    approx_data_point_ct: int | None
    can_access: bool | None


class TableGroupPreview(TypedDict):
    stats: StatsPreview
    tables: dict[str, TablePreview]
    success: bool
    message: str | None


def get_table_group_preview(
    table_group: TableGroup,
    connection: Connection | None = None,
    verify_table_access: bool = False,
) -> tuple[TableGroupPreview, Callable[[UUID], None]]:
    table_group_preview: TableGroupPreview = {
        "stats": {
            "id": table_group.id,
            "table_groups_name": table_group.table_groups_name,
            "table_group_schema": table_group.table_group_schema,
        },
        "tables": {},
        "success": True,
        "message": None,
    }
    save_data_chars = None

    if connection or table_group.connection_id:
        try:
            connection = connection or Connection.get(table_group.connection_id)
            table_group_preview, data_chars, sql_generator = _get_preview(table_group, connection)

            def save_data_chars(table_group_id: UUID) -> None:
                # Unsaved table groups will not have an ID, so we have to update it after saving
                sql_generator.table_group.id = table_group_id
                write_data_chars(data_chars, sql_generator, datetime.now(UTC))

            if verify_table_access:
                tables_preview = table_group_preview["tables"]
                for table_name in tables_preview.keys():
                    try:
                        results = fetch_from_target_db(connection, *sql_generator.verify_access(table_name))
                    except Exception as error:
                        tables_preview[table_name]["can_access"] = False
                    else:
                        tables_preview[table_name]["can_access"] = results is not None and len(results) > 0

                    if not all(table["can_access"] for table in tables_preview.values()):
                        table_group_preview["message"] = (
                            "Some tables were not accessible. Please the check the database permissions."
                        )
        except Exception as error:
            table_group_preview["success"] = False
            table_group_preview["message"] = error.args[0]
    else:
        table_group_preview["success"] = False
        table_group_preview["message"] = (
            "No connection selected. Please select a connection to preview the Table Group."
        )

    return table_group_preview, save_data_chars


def reset_table_group_preview() -> None:
    _get_preview.clear()


@st.cache_data(
    show_spinner=False,
    hash_funcs={
        TableGroup: lambda x: (
            x.table_group_schema,
            x.profiling_table_set,
            x.profiling_include_mask,
            x.profiling_exclude_mask,
        ),
        Connection: lambda x: x.to_dict(),
    },
)
def _get_preview(
    table_group: TableGroup,
    connection: Connection,
) -> tuple[TableGroupPreview, list[ColumnChars], RefreshDataCharsSQL]:
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    data_chars = fetch_from_target_db(connection, *sql_generator.get_schema_ddf())
    data_chars = [ColumnChars(**column) for column in data_chars]

    preview: TableGroupPreview = {
        "stats": {
            "id": table_group.id,
            "table_groups_name": table_group.table_groups_name,
            "table_group_schema": table_group.table_group_schema,
            "table_ct": 0,
            "column_ct": 0,
            "approx_record_ct": None,
            "approx_data_point_ct": None,
        },
        "tables": {},
        "success": True,
        "message": None,
    }
    stats = preview["stats"]
    tables = preview["tables"]

    for column in data_chars:
        if not tables.get(column.table_name):
            tables[column.table_name] = {
                "column_ct": 0,
                "approx_record_ct": column.approx_record_ct,
                "approx_data_point_ct": None,
                "can_access": None,
            }
            stats["table_ct"] += 1
            if column.approx_record_ct is not None:
                stats["approx_record_ct"] = (stats["approx_record_ct"] or 0) + column.approx_record_ct

        stats["column_ct"] += 1
        tables[column.table_name]["column_ct"] += 1
        if column.approx_record_ct is not None:
            stats["approx_data_point_ct"] = (stats["approx_data_point_ct"] or 0) + column.approx_record_ct
            tables[column.table_name]["approx_data_point_ct"] = (
                tables[column.table_name]["approx_data_point_ct"] or 0
            ) + column.approx_record_ct

    if len(data_chars) <= 0:
        preview["success"] = False
        preview["message"] = (
            "No tables found matching the criteria. Please check the Table Group configuration"
            " or the database permissions."
        )

    return preview, data_chars, sql_generator
