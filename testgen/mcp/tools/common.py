from uuid import UUID

import pandas as pd

from testgen.common.models.test_definition import TestType
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


def resolve_test_type(short_name: str) -> str:
    """Resolve a test type short name to its internal code."""
    matches = TestType.select_where(TestType.test_name_short == short_name)
    if not matches:
        raise MCPUserError(
            f"Unknown test type: `{short_name}`. Use the testgen://test-types resource to see available types."
        )
    return matches[0].test_type


def _escape_pipe(value: str) -> str:
    return value.replace("|", "\\|")


def build_markdown_table(
    headers: list[str],
    rows: list[list[str | None]],
    null_display: str = "—",
) -> str:
    """Build a markdown table from plain lists with pipe-escaping and null handling."""
    if not rows:
        return "_No rows._"

    def _cell(value: str | None) -> str:
        return _escape_pipe(str(value)) if value is not None else null_display

    header = "| " + " | ".join(_escape_pipe(h) for h in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def format_page_info(total: int, page: int, limit: int) -> str:
    """Shared pagination summary line for MCP tool output."""
    if total == 0:
        return ""
    start = (page - 1) * limit + 1
    end = min(start + limit - 1, total)
    return f"Showing {start}\u2013{end} of {total} (page {page}).\n"


def format_page_footer(total: int, page: int, limit: int) -> str:
    """Pagination footer hint — returns empty string if on the last page."""
    total_pages = (total + limit - 1) // limit
    if page >= total_pages:
        return ""
    return f"\n_Page {page} of {total_pages}. Use `page={page + 1}` for more._"


def dataframe_to_markdown(df: pd.DataFrame, null_display: str = "_NULL_") -> str:
    """Convert a DataFrame to a markdown table string."""
    if df is None or df.empty:
        return "_No rows._"

    cols = list(df.columns)
    header = "| " + " | ".join(_escape_pipe(str(c)) for c in cols) + " |"
    separator = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for _, row in df.iterrows():
        cells = " | ".join(_escape_pipe(str(v)) if pd.notna(v) else null_display for v in row)
        rows.append(f"| {cells} |")
    return "\n".join([header, separator, *rows])
