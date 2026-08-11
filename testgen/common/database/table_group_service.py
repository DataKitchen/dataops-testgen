"""Shared table-group helpers — common-layer logic shared by MCP, the UI, and
any future caller. Two pieces live here, both flavor-aware:

* ``validate_table_group_fields`` — required-field + format checks. Callers
  surface the returned bullets verbatim.
* ``preview_table_group`` — schema-introspection preview. Returns
  ``(preview, data_chars, sql_generator)``; the ``save_data_chars`` callback
  is built by callers via ``make_save_data_chars``.

None of these belong on the ``TableGroup`` model: preview opens an external
DB connection (I/O against an arbitrary target system), and the field-required
rules are form-shaped per-flavor logic, not model invariants.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID

from testgen.commands.queries.refresh_data_chars_query import RefreshDataCharsSQL
from testgen.commands.run_refresh_data_chars import write_data_chars
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.flavor.flavor_service import resolve_connection_params
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.ui.services.database_service import fetch_from_target_db

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_NAME_MIN = 3
_NAME_MAX = 40
_SAMPLE_PCT_MIN = 1
_SAMPLE_PCT_MAX = 100


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _coerce_int(value: object) -> int | None:
    """Return ``int(value)`` for ints / numeric strings, ``None`` otherwise.

    The model stores ``profiling_delay_days`` and ``profile_sample_percent`` as
    ``String`` columns; callers may pass either ints or numeric strings. Return
    ``None`` to signal "not parseable" so the validator can emit the right error.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (ValueError, AttributeError):
            return None
    return None


def validate_table_group_fields(table_group: TableGroup) -> list[str]:
    """Return every validation error (empty list = valid).

    Mirrors the per-field form validators on the UI ``Add Table Group`` wizard.
    The MCP tools call this and raise an ``MCPUserError`` containing the bullets
    — they never duplicate a rule themselves.
    """
    errors: list[str] = []

    name = table_group.table_groups_name
    if _missing(name):
        errors.append("`table_group_name` is required.")
    elif not (_NAME_MIN <= len(name.strip()) <= _NAME_MAX):
        errors.append(f"`table_group_name` must be between {_NAME_MIN} and {_NAME_MAX} characters.")

    if _missing(table_group.table_group_schema):
        errors.append("`schema` is required.")

    delay = _coerce_int(table_group.profiling_delay_days)
    if delay is None or delay < 0:
        errors.append("`profiling_delay_days` must be a non-negative integer.")

    pct = _coerce_int(table_group.profile_sample_percent)
    if pct is None or not (_SAMPLE_PCT_MIN <= pct <= _SAMPLE_PCT_MAX):
        errors.append(f"`profile_sample_percent` must be between {_SAMPLE_PCT_MIN} and {_SAMPLE_PCT_MAX}.")

    min_count = table_group.profile_sample_min_count
    if not isinstance(min_count, int) or isinstance(min_count, bool) or min_count < 0:
        errors.append("`profile_sample_min_count` must be a non-negative integer.")

    return errors


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


class StatsPreview(TypedDict, total=False):
    id: UUID | None
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


_NO_CONNECTION_MESSAGE = "No connection selected. Please select a connection to preview the Table Group."
_NO_TABLES_MESSAGE = (
    "No tables found matching the criteria. Please check the Table Group configuration"
    " or the database permissions."
)
_INACCESSIBLE_MESSAGE = "Some tables were not accessible. Please check the database permissions."


def preview_table_group(
    table_group: TableGroup,
    *,
    connection: Connection | None = None,
    verify_access: bool = True,
) -> tuple[TableGroupPreview, list[ColumnChars] | None, RefreshDataCharsSQL | None]:
    """Probe the connected target DB for tables matching ``table_group``'s filters.

    Returns ``(preview, data_chars, sql_generator)`` — three picklable values.
    No connection and DDF failure blank the second and third tuple elements; an
    empty schema still returns the empty list and the generator, and is signalled
    only by ``preview["success"]``. Check ``success``, not the elements.

    Use ``make_save_data_chars(data_chars, sql_generator)`` in callers that
    need to record the introspected metadata in ``data_chars``.
    """
    preview: TableGroupPreview = {
        "stats": {
            "id": table_group.id,
            "table_groups_name": table_group.table_groups_name,
            "table_group_schema": table_group.table_group_schema,
        },
        "tables": {},
        "success": True,
        "message": None,
    }

    if not (connection or table_group.connection_id):
        preview["success"] = False
        preview["message"] = _NO_CONNECTION_MESSAGE
        return preview, None, None

    data_chars: list[ColumnChars] | None = None
    sql_generator: RefreshDataCharsSQL | None = None
    try:
        if connection is None:
            connection = Connection.get(table_group.connection_id)
        preview, data_chars, sql_generator = _build_preview(table_group, connection)

        if verify_access and preview["success"]:
            for table_name in list(preview["tables"]):
                # The probe query completing is the access signal — an unreadable table
                # raises. Its result set is empty for an empty table, so row count says
                # nothing about access.
                try:
                    fetch_from_target_db(connection, *sql_generator.verify_access(table_name))
                except Exception:
                    preview["tables"][table_name]["can_access"] = False
                else:
                    preview["tables"][table_name]["can_access"] = True
            if not all(t["can_access"] for t in preview["tables"].values()):
                preview["message"] = _INACCESSIBLE_MESSAGE
    except Exception as error:
        preview["success"] = False
        preview["message"] = error.args[0] if error.args else str(error)
        data_chars = None
        sql_generator = None

    return preview, data_chars, sql_generator


def make_save_data_chars(
    data_chars: list[ColumnChars],
    sql_generator: RefreshDataCharsSQL,
) -> Callable[[UUID], None]:
    """Build the ``save_data_chars(table_group_id)`` callback for the caller.

    Kept out of ``preview_table_group`` so the service's return value stays
    picklable; local closures don't pickle.
    """
    def save(table_group_id: UUID) -> None:
        # Unsaved table groups won't have an ID yet; sync it before writing.
        sql_generator.table_group.id = table_group_id
        write_data_chars(data_chars, sql_generator, datetime.now(UTC))
    return save


def _build_preview(
    table_group: TableGroup,
    connection: Connection,
) -> tuple[TableGroupPreview, list[ColumnChars], RefreshDataCharsSQL]:
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    if sql_generator.flavor_service.metadata_via_api:
        params = resolve_connection_params(connection.__dict__)
        api_columns = sql_generator.flavor_service.get_schema_columns(params, table_group.table_group_schema) or []
        data_chars = sql_generator.filter_schema_columns(api_columns)
    else:
        rows = fetch_from_target_db(connection, *sql_generator.get_schema_ddf())
        data_chars = [ColumnChars(**column) for column in rows]

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
        preview["message"] = _NO_TABLES_MESSAGE

    return preview, data_chars, sql_generator
