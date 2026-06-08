"""Shared data catalog convenience service.

Generates CREATE TABLE scripts from profiled column metadata and fetches
sample rows from source tables. Used by both the Streamlit UI and MCP tools.
"""
import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import pandas as pd

from testgen.common.database.database_service import get_flavor_service
from testgen.common.database.flavor.flavor_service import FlavorService
from testgen.common.models.connection import Connection
from testgen.common.models.data_column import CreateScriptColumn, DataColumnChars
from testgen.common.pii_masking import get_pii_columns, mask_source_data_pii
from testgen.ui.services.database_service import fetch_from_target_db
from testgen.utils import to_dataframe

LOG = logging.getLogger("testgen")


@dataclass
class TableSampleResult:
    status: Literal["OK", "ND", "ERR"]
    message: str | None = None
    df: pd.DataFrame | None = None
    pii_redacted: bool = False


def render_create_table_script(
    schema_name: str,
    table_name: str,
    columns: list[CreateScriptColumn],
    flavor_service: FlavorService,
    *,
    annotate_changes: bool = False,
) -> str:
    """Render CREATE TABLE DDL from profiled columns, quoting identifiers for the flavor.

    Column types use the profiling-derived suggestion, falling back to the original
    database type. ``annotate_changes`` appends ``-- WAS <type>`` comments where the
    suggestion differs from the original type.
    """
    quote = flavor_service.quote_character
    table_ref = flavor_service.get_table_ref(schema_name, table_name)
    quoted_names = [f"{quote}{col.column_name}{quote}" for col in columns]

    name_width = max(len(name) for name in quoted_names)
    type_width = max(len(col.datatype_suggestion or col.db_data_type or "") for col in columns)

    col_defs = []
    for index, (col, name) in enumerate(zip(columns, quoted_names, strict=True)):
        col_type = col.datatype_suggestion or col.db_data_type or ""
        separator = "" if index == len(columns) - 1 else ","
        line = f"{name:<{name_width}} {col_type:<{type_width}}{separator}"
        if (
            annotate_changes
            and col.db_data_type
            and col.datatype_suggestion
            and col.db_data_type.lower() != col.datatype_suggestion.lower()
        ):
            line = f"{line}    -- WAS {col.db_data_type}"
        col_defs.append(line.rstrip())

    body = "\n    ".join(col_defs)
    return f"CREATE TABLE {table_ref} (\n    {body}\n);"


def build_create_table_script(
    table_group_id: UUID, table_name: str, *, annotate_changes: bool = False,
) -> str | None:
    """Build a CREATE TABLE script for a profiled table, or ``None`` if it is not in the catalog."""
    schema_name, columns = DataColumnChars.list_for_create_script(table_group_id, table_name)
    if not columns or schema_name is None:
        return None
    connection = Connection.get_by_table_group(table_group_id)
    if connection is None:
        return None
    flavor_service = get_flavor_service(connection.sql_flavor)
    return render_create_table_script(
        schema_name, table_name, columns, flavor_service, annotate_changes=annotate_changes,
    )


def fetch_table_sample(
    connection: Connection,
    table_group_id: UUID,
    schema_name: str,
    table_name: str,
    *,
    limit: int,
    mask_pii: bool,
    column_name: str | None = None,
) -> TableSampleResult:
    """Fetch distinct sample rows from a source table, masking PII columns when requested."""
    flavor_service = get_flavor_service(connection.sql_flavor)
    prefix, suffix = flavor_service.row_limit_clauses(limit)
    quote = flavor_service.quote_character
    table_ref = flavor_service.get_table_ref(schema_name, table_name)
    columns_expr = f"{quote}{column_name}{quote}" if column_name else "*"
    query = f"SELECT DISTINCT {prefix} {columns_expr} FROM {table_ref} {suffix}".strip()

    try:
        results = fetch_from_target_db(connection, query)
    except Exception:
        LOG.exception("Table sample fetch encountered an error.")
        return TableSampleResult("ERR", message="The sample data could not be loaded.")

    if not results:
        return TableSampleResult("ND")

    df = to_dataframe(results)
    pii_redacted = False
    if mask_pii:
        pii_columns = get_pii_columns(str(table_group_id), schema_name, table_name)
        pii_redacted = mask_source_data_pii(df, pii_columns)
    return TableSampleResult("OK", df=df, pii_redacted=pii_redacted)
