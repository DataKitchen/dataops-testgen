import base64
import io
import logging
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from testgen.common.models import with_database_session
from testgen.common.models.table_group import TableGroup
from testgen.ui.components.widgets.testgen_component import testgen_component
from testgen.ui.queries.profiling_queries import TAG_FIELDS
from testgen.ui.services.database_service import execute_db_query, fetch_all_from_db
from testgen.ui.services.rerun_service import safe_rerun
from testgen.ui.session import session, temp_value

LOG = logging.getLogger("testgen")

HEADER_MAP = {
    "table": "table_name",
    "column": "column_name",
    "description": "description",
    "critical data element": "critical_data_element",
    "cde": "critical_data_element",
    "excluded": "excluded_data_element",
    "excluded data element": "excluded_data_element",
    "xde": "excluded_data_element",
    "pii": "pii_flag",
    "pii flag": "pii_flag",
    "data source": "data_source",
    "source system": "source_system",
    "source process": "source_process",
    "business domain": "business_domain",
    "stakeholder group": "stakeholder_group",
    "transform level": "transform_level",
    "aggregation level": "aggregation_level",
    "data product": "data_product",    
}

METADATA_COLUMNS = ["description", "critical_data_element", "excluded_data_element", "pii_flag", *TAG_FIELDS]

TRUE_VALUES = {"yes", "y", "true", "1"}
FALSE_VALUES = {"no", "n", "false", "0"}

TAG_MAX_LENGTH = 40
DESCRIPTION_MAX_LENGTH = 1000


def parse_import_csv(content: str, table_group_id: str, blank_behavior: str) -> dict:
    parsed = _parse_csv(content)
    if "error" in parsed:
        return parsed

    return _match_and_validate(parsed["df"], parsed["duplicate_rows"], table_group_id, blank_behavior)


def _parse_csv(content: str) -> dict:
    try:
        raw_bytes = base64.b64decode(content.split(",")[1])
        df = pd.read_csv(io.BytesIO(raw_bytes), dtype=str, keep_default_na=False)
    except Exception as e:
        LOG.warning("CSV parse error: %s", e)
        return {"error": f"Could not parse CSV file: {e}"}

    # Normalize headers
    normalized_columns = {}
    for col in df.columns:
        key = col.strip().lower().replace("_", " ")
        mapped = HEADER_MAP.get(key)
        if mapped:
            normalized_columns[col] = mapped

    if "table_name" not in normalized_columns.values():
        return {"error": "CSV must contain a 'Table' column."}

    df = df.rename(columns=normalized_columns)
    # Keep only recognized columns
    recognized = [c for c in df.columns if c in ("table_name", "column_name", *METADATA_COLUMNS)]
    df = df[recognized]

    if df.empty:
        return {"error": "CSV file is empty."}

    # Strip whitespace from all string fields
    for col in df.columns:
        df[col] = df[col].str.strip()

    # Deduplicate: last occurrence wins, mark earlier duplicates
    has_column_name = "column_name" in df.columns
    if not has_column_name:
        df["column_name"] = ""
    dedup_cols = ["table_name", "column_name"] if has_column_name else ["table_name"]
    is_last = ~df.duplicated(subset=dedup_cols, keep="last")
    duplicate_rows = df[~is_last]
    df = df[is_last]

    return {"df": df, "duplicate_rows": duplicate_rows}


def _match_and_validate(
    df: pd.DataFrame, duplicate_rows: pd.DataFrame, table_group_id: str, blank_behavior: str
) -> dict:
    # Query existing tables and columns in this table group
    existing_tables = fetch_all_from_db(
        """
        SELECT table_id::VARCHAR, table_name
        FROM data_table_chars
        WHERE table_groups_id = :table_group_id
        """,
        {"table_group_id": table_group_id},
    )
    table_lookup = {row["table_name"]: row["table_id"] for row in existing_tables}

    existing_columns = fetch_all_from_db(
        """
        SELECT column_id::VARCHAR, table_name, column_name
        FROM data_column_chars
        WHERE table_groups_id = :table_group_id
        """,
        {"table_group_id": table_group_id},
    )
    column_lookup = {(row["table_name"], row["column_name"]): row["column_id"] for row in existing_columns}

    table_rows = []
    column_rows = []
    preview_rows = []

    for _, dup_row in duplicate_rows.iterrows():
        preview_rows.append({
            "table_name": dup_row["table_name"],
            "column_name": dup_row.get("column_name", ""),
            "_status": "unmatched",
            "_status_detail": "Duplicate row \u2014 last occurrence will be used",
            "_truncated_fields": [],
        })

    for _, row in df.iterrows():
        table_name = row["table_name"]
        column_name = row.get("column_name", "")

        if not table_name:
            continue

        is_table_row = not column_name
        preview_row = {"table_name": table_name, "column_name": column_name or ""}

        if is_table_row:
            table_id = table_lookup.get(table_name)
            if not table_id:
                preview_row["_status"] = "unmatched"
                preview_row["_status_detail"] = "Table not found in catalog"
                preview_rows.append(preview_row)
                continue

            fields, bad_cde, bad_xde, bad_pii = _extract_metadata_fields(row, blank_behavior)
            fields, truncated = _truncate_fields(fields)
            if fields and not bad_cde and not bad_xde and not bad_pii:
                table_rows.append({"table_id": table_id, "table_name": table_name, **fields})

            preview_row.update(fields)
            _set_row_status(preview_row, bad_cde, bad_xde, bad_pii, truncated)
            preview_rows.append(preview_row)
        else:
            column_id = column_lookup.get((table_name, column_name))
            if not column_id:
                preview_row["_status"] = "unmatched"
                preview_row["_status_detail"] = (
                    "Table not found in catalog" if table_name not in table_lookup else "Column not found in catalog"
                )
                preview_rows.append(preview_row)
                continue

            fields, bad_cde, bad_xde, bad_pii = _extract_metadata_fields(row, blank_behavior)
            fields, truncated = _truncate_fields(fields)
            if fields and not bad_cde and not bad_xde and not bad_pii:
                column_rows.append(
                    {"column_id": column_id, "table_name": table_name, "column_name": column_name, **fields}
                )

            preview_row.update(fields)
            _set_row_status(preview_row, bad_cde, bad_xde, bad_pii, truncated)
            preview_rows.append(preview_row)

    # Determine which metadata columns are present in the CSV
    metadata_columns = [c for c in METADATA_COLUMNS if c in df.columns]

    # Strip PII column if user lacks permission
    pii_skipped = False
    if "pii_flag" in metadata_columns and not session.auth.user_has_permission("view_pii"):
        metadata_columns.remove("pii_flag")
        pii_skipped = True

    # Count matched vs skipped rows from preview
    # "ok" and "warning" rows will be imported; "error" and "unmatched" rows are skipped
    _importable = {"ok", "warning"}
    matched_tables = sum(1 for r in preview_rows if not r.get("column_name") and r.get("_status") in _importable)
    matched_columns = sum(1 for r in preview_rows if r.get("column_name") and r.get("_status") in _importable)
    skipped = sum(1 for r in preview_rows if r.get("_status") not in _importable)

    table_group = TableGroup.get(table_group_id)

    return {
        "table_rows": table_rows,
        "column_rows": column_rows,
        "preview_rows": preview_rows,
        "metadata_columns": metadata_columns,
        "blank_behavior": blank_behavior,
        "matched_tables": matched_tables,
        "matched_columns": matched_columns,
        "skipped_count": skipped,
        "warn_cde": bool("critical_data_element" in metadata_columns and table_group.profile_flag_cdes),
        "warn_pii": bool("pii_flag" in metadata_columns and table_group.profile_flag_pii),
        "pii_skipped": pii_skipped,
    }


def _extract_metadata_fields(row: pd.Series, blank_behavior: str) -> tuple[dict, bool, bool, bool]:
    fields = {}
    bad_cde = False
    bad_xde = False
    bad_pii = False
    for col in METADATA_COLUMNS:
        if col not in row.index:
            continue

        value = row[col]

        if col == "critical_data_element":
            if value.lower() in TRUE_VALUES:
                fields[col] = True
            elif value.lower() in FALSE_VALUES:
                fields[col] = False
            elif not value:
                if blank_behavior == "clear":
                    fields[col] = None
                # "keep" → skip this field
            else:
                # Unrecognized value — skip (don't set field at all)
                bad_cde = True
        elif col == "excluded_data_element":
            if value.lower() in TRUE_VALUES:
                fields[col] = True
            elif value.lower() in FALSE_VALUES:
                fields[col] = False
            elif not value:
                if blank_behavior == "clear":
                    fields[col] = False
            else:
                bad_xde = True
        elif col == "pii_flag":
            if value.lower() in TRUE_VALUES:
                fields[col] = "MANUAL"
            elif value.lower() in FALSE_VALUES:
                fields[col] = None
            elif not value:
                if blank_behavior == "clear":
                    fields[col] = None
            else:
                bad_pii = True
        else:
            if value:
                fields[col] = value
            elif blank_behavior == "clear":
                fields[col] = ""
            # "keep" with blank value → skip this field

    return fields, bad_cde, bad_xde, bad_pii


def _truncate_fields(fields: dict) -> tuple[dict, list[str]]:
    truncated = []
    for key, value in fields.items():
        if not isinstance(value, str):
            continue
        max_len = DESCRIPTION_MAX_LENGTH if key == "description" else TAG_MAX_LENGTH
        if len(value) > max_len:
            fields[key] = value[:max_len]
            truncated.append(key)
    return fields, truncated


def _set_row_status(preview_row: dict, bad_cde: bool, bad_xde: bool, bad_pii: bool, truncated: list[str]) -> None:
    issues = []
    if bad_cde:
        issues.append("Unrecognized CDE value (expected Yes/No) — skipped")
    if bad_xde:
        issues.append("Unrecognized XDE value (expected Yes/No) - skipped")
    if bad_pii:
        issues.append("Unrecognized PII value (expected Yes/No) - skipped")
    if truncated:
        issues.append(f"Values truncated: {', '.join(truncated)}")

    if bad_cde or bad_xde or bad_pii:
        preview_row["_status"] = "error"
    elif truncated:
        preview_row["_status"] = "warning"
    else:
        preview_row["_status"] = "ok"
    preview_row["_status_detail"] = "\n".join(issues)
    preview_row["_truncated_fields"] = truncated


def apply_metadata_import(preview: dict, table_group_id: str | None = None) -> dict:
    table_count = 0
    column_count = 0

    for row in preview.get("table_rows", []):
        set_clauses, params = _build_update_params(row, preview["metadata_columns"], is_column=False)
        if not set_clauses:
            continue
        params["table_id"] = row["table_id"]
        execute_db_query(
            f"UPDATE data_table_chars SET {', '.join(set_clauses)} WHERE table_id = CAST(:table_id AS UUID)",
            params,
        )
        table_count += 1

    for row in preview.get("column_rows", []):
        set_clauses, params = _build_update_params(row, preview["metadata_columns"], is_column=True)
        if not set_clauses:
            continue
        params["column_id"] = row["column_id"]
        execute_db_query(
            f"UPDATE data_column_chars SET {', '.join(set_clauses)} WHERE column_id = CAST(:column_id AS UUID)",
            params,
        )
        column_count += 1

    if table_group_id:
        _disable_autoflags(table_group_id, preview.get("metadata_columns", []))

    return {"table_count": table_count, "column_count": column_count}


def _disable_autoflags(table_group_id: str, metadata_columns: list[str]) -> None:
    table_group = TableGroup.get(table_group_id)
    changed = False
    if "critical_data_element" in metadata_columns and table_group.profile_flag_cdes:
        table_group.profile_flag_cdes = False
        changed = True
    if "pii_flag" in metadata_columns and table_group.profile_flag_pii:
        table_group.profile_flag_pii = False
        changed = True
    if changed:
        table_group.save()


def _build_update_params(row: dict, metadata_columns: list[str], is_column: bool = False) -> tuple[list[str], dict]:
    set_clauses = []
    params = {}

    for col in metadata_columns:
        if col not in row:
            continue

        value = row[col]
        if col == "critical_data_element":
            set_clauses.append("critical_data_element = :critical_data_element")
            params["critical_data_element"] = value
        elif col == "excluded_data_element":
            if is_column:
                set_clauses.append("excluded_data_element = :excluded_data_element")
                params["excluded_data_element"] = value
        elif col == "pii_flag":
            # Prevent user from editing PII flag if they cannot view PII
            if is_column and session.auth.user_has_permission("view_pii"):
                set_clauses.append("pii_flag = :pii_flag")
                params["pii_flag"] = value
        else:
            set_clauses.append(f"{col} = NULLIF(:{col}, '')")
            params[col] = value if value is not None else ""

    return set_clauses, params


PREVIEW_SESSION_KEY = "import_metadata:preview"


def open_import_metadata_dialog(table_group_id: str) -> None:
    """Clear stale preview state before opening the dialog."""
    st.session_state.pop(PREVIEW_SESSION_KEY, None)
    import_metadata_dialog(table_group_id)


@st.dialog(title="Import Metadata", width="large")
@with_database_session
def import_metadata_dialog(table_group_id: str) -> None:
    should_import, set_should_import = temp_value("import_metadata:import")

    def on_file_uploaded(payload: dict) -> None:
        content = payload["content"]
        blank_behavior = payload["blank_behavior"]
        preview = parse_import_csv(content, table_group_id, blank_behavior)
        st.session_state[PREVIEW_SESSION_KEY] = preview

    def on_file_cleared(_payload: dict) -> None:
        st.session_state.pop(PREVIEW_SESSION_KEY, None)

    # Preview persists in session state (not temp_value) so it survives across reruns
    preview = st.session_state.get(PREVIEW_SESSION_KEY)

    result = None
    if should_import() and preview and not preview.get("error"):
        try:
            apply_metadata_import(preview, table_group_id)

            # Clear caches
            from testgen.ui.queries.profiling_queries import get_column_by_id, get_table_by_id
            from testgen.ui.views.data_catalog import get_table_group_columns, get_tag_values

            for func in [get_table_group_columns, get_table_by_id, get_column_by_id, get_tag_values]:
                func.clear()
            st.session_state["data_catalog:last_saved_timestamp"] = datetime.now().timestamp()

            parts = []
            if tc := preview.get("matched_tables", 0):
                parts.append(f"{tc} {'table' if tc == 1 else 'tables'}")
            if cc := preview.get("matched_columns", 0):
                parts.append(f"{cc} {'column' if cc == 1 else 'columns'}")
            summary = f"Metadata for {', '.join(parts)} imported." if parts else "No metadata was imported."

            result = {
                "success": True,
                "message": summary,
            }
        except Exception:
            LOG.exception("Metadata import failed")
            result = {
                "success": False,
                "message": "Something went wrong while importing the metadata.",
            }

        st.session_state.pop(PREVIEW_SESSION_KEY, None)

    # Build preview data for JS display
    preview_props = None
    if preview:
        if preview.get("error"):
            preview_props = {"error": preview["error"]}
        else:
            preview_props = _build_preview_props(preview)

    testgen_component(
        "import_metadata_dialog",
        props={
            "preview": preview_props,
            "result": result,
        },
        on_change_handlers={
            "FileUploaded": on_file_uploaded,
            "FileCleared": on_file_cleared,
            "ImportConfirmed": lambda _: set_should_import(True),
        },
    )

    if result and result["success"]:
        time.sleep(2)
        safe_rerun()


def _build_preview_props(preview: dict) -> dict:
    formatted_rows = []
    metadata_columns = preview.get("metadata_columns", [])

    for row in preview.get("preview_rows", []):
        formatted_row = {
            "table_name": row["table_name"],
            "column_name": row["column_name"],
            "_status": row.get("_status", "ok"),
            "_status_detail": row.get("_status_detail", ""),
            "_truncated_fields": row.get("_truncated_fields", []),
        }
        for col in metadata_columns:
            if col in row:
                val = row[col]
                if col in ["excluded_data_element", "pii_flag"]:
                    formatted_row[col] = "Yes" if val else "No"
                else:
                    formatted_row[col] = (
                        "Yes" if val is True else "No" if val is False else ("" if val is None else str(val))
                    )
        formatted_rows.append(formatted_row)

    return {
        "table_count": preview.get("matched_tables", 0),
        "column_count": preview.get("matched_columns", 0),
        "skipped_count": preview.get("skipped_count", 0),
        "metadata_columns": metadata_columns,
        "preview_rows": formatted_rows,
        "warn_cde": preview.get("warn_cde", False),
        "warn_pii": preview.get("warn_pii", False),
        "pii_skipped": preview.get("pii_skipped", False),
    }
