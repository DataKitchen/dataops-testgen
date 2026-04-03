from uuid import UUID

import pandas as pd

from testgen.common.models.test_result import TestResultStatus
from testgen.mcp.exceptions import MCPUserError


def parse_uuid(value: str, label: str = "ID") -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError) as err:
        raise MCPUserError(f"Invalid {label}: `{value}` is not a valid UUID.") from err


def parse_result_status(value: str) -> TestResultStatus:
    try:
        return TestResultStatus(value)
    except ValueError as err:
        valid = ", ".join(s.value for s in TestResultStatus)
        raise MCPUserError(f"Invalid status `{value}`. Valid values: {valid}") from err


def dataframe_to_markdown(df: pd.DataFrame, null_display: str = "_NULL_") -> str:
    """Convert a DataFrame to a markdown table string."""
    if df is None or df.empty:
        return "_No rows._"

    def _escape(value: str) -> str:
        return value.replace("|", "\\|")

    cols = list(df.columns)
    header = "| " + " | ".join(_escape(str(c)) for c in cols) + " |"
    separator = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for _, row in df.iterrows():
        cells = " | ".join(_escape(str(v)) if pd.notna(v) else null_display for v in row)
        rows.append(f"| {cells} |")
    return "\n".join([header, separator, *rows])
