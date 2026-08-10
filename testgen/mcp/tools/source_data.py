from datetime import datetime
from typing import Annotated

from pydantic import Field

from testgen.common.data_catalog_service import fetch_table_sample
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.test_definition import TestDefinition
from testgen.common.source_data_service import (
    SourceDataResult,
    build_hygiene_query,
    build_test_result_query,
    fetch_hygiene_source_data,
    fetch_test_result_source_data,
)
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    parse_uuid,
    resolve_hygiene_issue,
    resolve_table_group,
    validate_limit,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.INVESTIGATE


def _validate_source_args(test_definition_id: str | None, issue_id: str | None, reference_date: str | None) -> None:
    """Enforce 'exactly one entity' and the reference_date-only-with-test-definition rule."""
    if bool(test_definition_id) == bool(issue_id):
        raise MCPUserError("Provide exactly one of test_definition_id or issue_id.")
    if issue_id and reference_date:
        raise MCPUserError(
            "reference_date applies only to test_definition_id; omit it when looking up a hygiene issue."
        )


def _resolve_test_definition_context(test_definition_id: str, reference_date: str | None) -> dict:
    """Look up the test definition context and validate permissions."""
    td_uuid = parse_uuid(test_definition_id, "test_definition_id")
    perms = get_project_permissions()

    context = TestDefinition.get_source_data_context(td_uuid, project_codes=perms.allowed_codes)
    if context is None:
        raise MCPResourceNotAccessible("Test definition", test_definition_id)

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


def _resolve_hygiene_context(issue_id: str) -> dict:
    """Resolve a hygiene issue (permission-scoped) into the lookup context the service expects.

    The source profiling run is intrinsic to the issue, so ``profiling_starttime`` comes from the
    issue's ``ProfilingRun`` — there is no caller-supplied reference date.
    """
    issue = resolve_hygiene_issue(issue_id)
    run = ProfilingRun.get(issue.profile_run_id)
    return {
        "table_groups_id": issue.table_groups_id,
        "anomaly_id": issue.type_id,
        "detail": issue.detail,
        "schema_name": issue.schema_name,
        "table_name": issue.table_name,
        "column_name": issue.column_name,
        "profiling_starttime": run.profiling_starttime if run else None,
        "project_code": issue.project_code,
    }


def _render_header_fields(doc: MdDoc, context: dict) -> None:
    """Render the entity-neutral location fields shared by both tools."""
    if context.get("test_type"):
        doc.field("Test type", context.get("test_type"), code=True)
    doc.field("Table", f"{context.get('schema_name')}.{context.get('table_name')}", code=True)
    column = context.get("column_names") or context.get("column_name")
    if column:
        doc.field("Column", column, code=True)


@with_database_session
@mcp_permission("view")
def get_source_data_query(
    test_definition_id: Annotated[
        str | None,
        Field(description="UUID of a test definition, e.g. from ``list_test_results``."),
    ] = None,
    issue_id: Annotated[
        str | None,
        Field(
            description="UUID of a hygiene issue, e.g. from ``list_hygiene_issues``. Mutually exclusive with "
            "``test_definition_id``.",
        ),
    ] = None,
    reference_date: Annotated[
        str | None,
        Field(
            description="ISO 8601 date used as the test reference point (default: now). Applies only to "
            "``test_definition_id``.",
        ),
    ] = None,
    limit: Annotated[int, Field(description="Maximum rows the query would return (default 100, max 500).")] = 100,
) -> str:
    """Get the SQL query that would look up source data, without executing it.

    Builds a lookup query using the current criteria of a test definition or a hygiene issue.
    The query targets the connected database.
    Some test types (e.g. Freshness Trend, Schema Drift) do not have source data lookups.

    Provide exactly one of ``test_definition_id`` or ``issue_id``.
    """
    _validate_source_args(test_definition_id, issue_id, reference_date)
    validate_limit(limit, 500)

    if test_definition_id:
        context = _resolve_test_definition_context(test_definition_id, reference_date)
        entity_label, entity_id = "Test Definition", test_definition_id
        query = build_test_result_query(context, limit)
    else:
        context = _resolve_hygiene_context(issue_id)
        entity_label, entity_id = "Hygiene Issue", issue_id
        query = build_hygiene_query(context, limit)

    if not query:
        if test_definition_id:
            return (
                f"Source data lookup is not available for test type `{context.get('test_type', 'unknown')}`.\n\n"
                "This test type does not have a defined lookup query."
            )
        return (
            "Source data lookup is not available for this hygiene issue.\n\n"
            "This hygiene issue type does not have a defined lookup query."
        )

    doc = MdDoc()
    doc.heading(1, f"Source Data Query for {entity_label} `{entity_id}`")
    _render_header_fields(doc, context)
    doc.field("Limit", limit)
    doc.code_block(query, language="sql")

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_source_data(
    test_definition_id: Annotated[
        str | None,
        Field(description="UUID of a test definition, e.g. from ``list_test_results``."),
    ] = None,
    issue_id: Annotated[
        str | None,
        Field(
            description="UUID of a hygiene issue, e.g. from ``list_hygiene_issues``. Mutually exclusive with "
            "``test_definition_id``.",
        ),
    ] = None,
    reference_date: Annotated[
        str | None,
        Field(
            description="ISO 8601 date used as the test reference point (default: now). Applies only to "
            "``test_definition_id``.",
        ),
    ] = None,
    limit: Annotated[int, Field(description="Maximum rows to return (default 100, max 500).")] = 100,
) -> str:
    """Look up rows that match or violate a test or hygiene issue's criteria.
    Rows are read from the connected database.

    Executes the source data query against the connected database and returns matching rows.
    Shows CURRENT data — rows may have changed since the test or profiling run.
    Some test types (e.g. Freshness Trend, Schema Drift) do not have source data lookups.

    Provide exactly one of ``test_definition_id`` or ``issue_id``.
    """
    _validate_source_args(test_definition_id, issue_id, reference_date)
    validate_limit(limit, 500)

    if test_definition_id:
        context = _resolve_test_definition_context(test_definition_id, reference_date)
        entity_label, entity_id = "Test Definition", test_definition_id
        fetch = fetch_test_result_source_data
    else:
        context = _resolve_hygiene_context(issue_id)
        entity_label, entity_id = "Hygiene Issue", issue_id
        fetch = fetch_hygiene_source_data

    mask_pii = not get_project_permissions().has_permission("view_pii", context.get("project_code"))

    result: SourceDataResult = fetch(context, limit, mask_pii)

    doc = MdDoc()
    doc.heading(1, f"Source Data for {entity_label} `{entity_id}`")
    _render_header_fields(doc, context)

    if result.status == "OK":
        row_count = len(result.df) if result.df is not None else 0
        doc.field("Rows returned", row_count)
        if result.pii_redacted:
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


@with_database_session
@mcp_permission("catalog")
def get_table_sample(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    table_name: Annotated[str, Field(description="Table name exactly as stored in TestGen (case-sensitive).")],
    limit: Annotated[int, Field(description="Maximum rows to return (default 100, max 500).")] = 100,
) -> str:
    """Fetch sample rows from a source table for inspection."""
    validate_limit(limit, 500)
    tg = resolve_table_group(table_group_id)

    schema_name, _ = DataColumnChars.list_for_create_script(tg.id, table_name)
    if schema_name is None:
        raise MCPResourceNotAccessible("Table", table_name)

    connection = Connection.get_by_table_group(tg.id)
    if connection is None:
        raise MCPResourceNotAccessible("Table", table_name)

    mask_pii = not get_project_permissions().has_permission("view_pii", tg.project_code)
    result = fetch_table_sample(
        connection, tg.id, schema_name, table_name, limit=limit, mask_pii=mask_pii,
    )

    if result.status == "ERR":
        raise MCPUserError(
            f"Could not read from the source database for connection `{connection.connection_name}`."
        )

    doc = MdDoc()
    if result.status == "ND":
        return doc.text("Table has no rows.").render()

    row_count = len(result.df) if result.df is not None else 0
    doc.field("Rows returned", row_count)
    if result.pii_redacted:
        doc.text("_PII columns have been redacted._")
    doc.table_from_dataframe(result.df)
    return doc.render()
