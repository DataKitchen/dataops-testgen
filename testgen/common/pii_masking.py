"""PII masking utilities for redacting sensitive data in the UI."""
import pandas as pd

from testgen.ui.services.database_service import fetch_all_from_db

PII_REDACTED = "[PII Redacted]"

PROFILING_PII_FIELDS = (
    "top_freq_values", "min_text", "max_text",
    "min_value", "min_value_over_0", "max_value",
    "min_date", "max_date",
)


def get_pii_columns(table_group_id: str, schema: str | None = None, table_name: str | None = None) -> set[str]:
    """Look up PII-flagged column names from data_column_chars."""

    query = f"""
    SELECT column_name
    FROM data_column_chars
    WHERE table_groups_id = :table_group_id
        AND pii_flag IS NOT NULL
        {"AND schema_name = :schema" if schema else ""}
        {"AND table_name = :table_name" if table_name else ""}
    """
    params: dict = {
        "table_group_id": table_group_id,
        "schema": schema,
        "table_name": table_name,
    }

    results = fetch_all_from_db(query, params)
    return {row.column_name for row in results}


def mask_dataframe_pii(df: pd.DataFrame, pii_columns: set[str]) -> None:
    """In-place mask values in PII columns with PII_REDACTED."""
    if df.empty or not pii_columns:
        return
    for col in pii_columns:
        # Match case-insensitively since column names may differ in case
        for df_col in df.columns:
            if df_col.lower() == col.lower():
                df[df_col] = PII_REDACTED


def mask_profiling_pii(data: pd.DataFrame | dict, pii_columns: set[str]) -> None:
    """Mask profiling fields for PII columns. Accepts a DataFrame or a single-row dict."""
    if isinstance(data, dict):
        if not pii_columns:
            return
        column_name = data.get("column_name")
        if column_name and column_name.lower() not in {c.lower() for c in pii_columns}:
            return
        for field in PROFILING_PII_FIELDS:
            if field in data:
                data[field] = PII_REDACTED
        return

    if data.empty or not pii_columns:
        return
    pii_lower = {c.lower() for c in pii_columns}
    mask = data["column_name"].str.lower().isin(pii_lower)
    for field in PROFILING_PII_FIELDS:
        if field in data.columns:
            if data[field].dtype != object:
                data[field] = data[field].astype(object)
            data.loc[mask, field] = PII_REDACTED
