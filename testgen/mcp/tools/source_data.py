from datetime import datetime

from testgen.common.models import with_database_session
from testgen.common.models.test_definition import TestDefinition
from testgen.common.source_data_service import (
    SourceDataResult,
    build_test_result_query,
    fetch_test_result_source_data,
)
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import dataframe_to_markdown, parse_uuid


def _resolve_context(test_definition_id: str, reference_date: str | None) -> dict:
    """Look up the test definition context and validate permissions."""
    td_uuid = parse_uuid(test_definition_id, "test_definition_id")
    perms = get_project_permissions()

    context = TestDefinition.get_source_data_context(td_uuid, project_codes=perms.allowed_codes)
    if context is None:
        raise MCPUserError(f"Test definition `{test_definition_id}` not found or not accessible.")

    if reference_date:
        try:
            test_date = datetime.fromisoformat(reference_date)
        except ValueError as err:
            raise MCPUserError(
                f"Invalid reference_date: `{reference_date}`. Use ISO 8601 format (e.g. '2025-01-15' or '2025-01-15T00:00:00')."
            ) from err
    else:
        test_date = datetime.now()

    # The source data service expects test_date as a datetime (parse_fuzzy_date passes it through)
    context["test_date"] = test_date

    return context


@with_database_session
@mcp_permission("view")
def get_source_data_query(
    test_definition_id: str,
    reference_date: str | None = None,
    limit: int = 100,
) -> str:
    """Get the SQL query that would be used to look up source data for a test definition, without executing it.

    Builds a lookup query using current test definition parameters (thresholds, conditions).
    The query targets the connected database (Snowflake, BigQuery, Postgres, etc.).
    Some test types (e.g. Freshness Trend, Schema Drift) do not have source data lookups.

    Args:
        test_definition_id: UUID of the test definition (from get_test_results output).
        reference_date: ISO 8601 date used as the test reference point (default: now).
        limit: Maximum rows the query would return (default 100, max 500).
    """
    limit = min(max(limit, 1), 500)
    context = _resolve_context(test_definition_id, reference_date)

    query = build_test_result_query(context, limit)
    if not query:
        return (
            f"Source data lookup is not available for test type `{context.get('test_type', 'unknown')}`.\n\n"
            "This test type does not have a defined lookup query."
        )

    lines = [
        f"# Source Data Query for Test Definition `{test_definition_id}`\n",
        f"- **Test type:** `{context.get('test_type')}`",
        f"- **Table:** `{context.get('schema_name')}`.`{context.get('table_name')}`",
    ]
    if context.get("column_names"):
        lines.append(f"- **Column:** `{context['column_names']}`")
    lines.append(f"- **Limit:** {limit}")
    lines.append(f"\n```sql\n{query}\n```")

    return "\n".join(lines)


@with_database_session
@mcp_permission("view")
def get_source_data(
    test_definition_id: str,
    reference_date: str | None = None,
    limit: int = 100,
) -> str:
    """Look up rows from the connected database that match or violate a test definition's criteria.

    Executes the source data query against the connected database and returns matching rows.
    Shows CURRENT data — rows may have changed since the test last ran.
    Some test types (e.g. Freshness Trend, Schema Drift) do not have source data lookups.

    Args:
        test_definition_id: UUID of the test definition (from get_test_results output).
        reference_date: ISO 8601 date used as the test reference point (default: now).
        limit: Maximum rows to return (default 100, max 500).
    """
    limit = min(max(limit, 1), 500)
    context = _resolve_context(test_definition_id, reference_date)

    perms = get_project_permissions()
    mask_pii = context.get("project_code") not in perms.codes_allowed_to("view_pii")

    result: SourceDataResult = fetch_test_result_source_data(context, limit, mask_pii)

    lines = [f"# Source Data for Test Definition `{test_definition_id}`\n"]
    lines.append(f"- **Test type:** `{context.get('test_type')}`")
    lines.append(f"- **Table:** `{context.get('schema_name')}`.`{context.get('table_name')}`")
    if context.get("column_names"):
        lines.append(f"- **Column:** `{context['column_names']}`")

    if result.status == "OK":
        row_count = len(result.df) if result.df is not None else 0
        lines.append(f"- **Rows returned:** {row_count}")
        if mask_pii:
            lines.append("- _PII columns have been redacted._")
        lines.append("")
        lines.append(dataframe_to_markdown(result.df))
        if result.query:
            lines.append(f"\n**Query used:**\n```sql\n{result.query}\n```")
    elif result.status == "NA":
        lines.append(f"\n{result.message}")
    elif result.status == "ND":
        lines.append(f"\n{result.message}")
        if result.query:
            lines.append(f"\n**Query used:**\n```sql\n{result.query}\n```")
    elif result.status == "ERR":
        lines.append(f"\n**Error:** {result.message}")
        if result.query:
            lines.append(f"\n**Query used:**\n```sql\n{result.query}\n```")

    return "\n".join(lines)
