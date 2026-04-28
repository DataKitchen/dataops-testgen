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
from testgen.mcp.tools.common import parse_uuid
from testgen.mcp.tools.markdown import MdDoc


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
    The query targets the connected database.
    Some test types (e.g. Freshness Trend, Schema Drift) do not have source data lookups.

    Args:
        test_definition_id: UUID of a test definition, e.g. from ``list_test_results``.
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

    doc = MdDoc()
    doc.heading(1, f"Source Data Query for Test Definition `{test_definition_id}`")
    doc.field("Test type", context.get("test_type"), code=True)
    doc.field("Table", f"{context.get('schema_name')}.{context.get('table_name')}", code=True)
    if context.get("column_names"):
        doc.field("Column", context["column_names"], code=True)
    doc.field("Limit", limit)
    doc.code_block(query, language="sql")

    return doc.render()


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
        test_definition_id: UUID of a test definition, e.g. from ``list_test_results``.
        reference_date: ISO 8601 date used as the test reference point (default: now).
        limit: Maximum rows to return (default 100, max 500).
    """
    limit = min(max(limit, 1), 500)
    context = _resolve_context(test_definition_id, reference_date)

    perms = get_project_permissions()
    mask_pii = context.get("project_code") not in perms.codes_allowed_to("view_pii")

    result: SourceDataResult = fetch_test_result_source_data(context, limit, mask_pii)

    doc = MdDoc()
    doc.heading(1, f"Source Data for Test Definition `{test_definition_id}`")
    doc.field("Test type", context.get("test_type"), code=True)
    doc.field("Table", f"{context.get('schema_name')}.{context.get('table_name')}", code=True)
    if context.get("column_names"):
        doc.field("Column", context["column_names"], code=True)

    if result.status == "OK":
        row_count = len(result.df) if result.df is not None else 0
        doc.field("Rows returned", row_count)
        if mask_pii:
            doc.text("_PII columns have been redacted._")
        doc.table_from_dataframe(result.df)
        if result.query:
            doc.text("**Query used:**")
            doc.code_block(result.query, language="sql")
    elif result.status == "NA":
        doc.text(result.message)
    elif result.status == "ND":
        doc.text(result.message)
        if result.query:
            doc.text("**Query used:**")
            doc.code_block(result.query, language="sql")
    elif result.status == "ERR":
        doc.text(f"**Error:** {result.message}")
        if result.query:
            doc.text("**Query used:**")
            doc.code_block(result.query, language="sql")

    return doc.render()
