from testgen.common.models import with_database_session
from testgen.common.models.test_definition import TestDefinition, TestDefinitionNote, TestDefinitionSummary, TestType
from testgen.common.models.test_result import TestResult
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools import DocGroup
from testgen.mcp.tools.common import (
    format_page_footer,
    format_page_info,
    parse_uuid,
    resolve_test_type,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.DISCOVER

_VALID_SCOPES = {"column", "table", "referential", "custom"}
_VALID_IMPACT_DIMENSIONS = {"Reliability", "Conformance", "Regularity", "Usability"}
_VALID_DQ_DIMENSIONS = {"Accuracy", "Completeness", "Consistency", "Recency", "Timeliness", "Uniqueness", "Validity"}


@with_database_session
@mcp_permission("view")
def list_tests(
    test_suite_id: str,
    table_name: str | None = None,
    test_type: str | None = None,
    test_active: bool | None = None,
    limit: int = 50,
    page: int = 1,
) -> str:
    """List test definitions in a test suite.

    Args:
        test_suite_id: The UUID of the test suite.
        table_name: Filter by table name (exact match).
        test_type: Filter by test type (e.g. 'Alpha Truncation', 'Row Count').
        test_active: Filter by active status (true/false). Omit to show all.
        limit: Maximum number of tests per page (default 50, max 200).
        page: Page number, starting from 1 (default 1).
    """
    suite_uuid = parse_uuid(test_suite_id, "test_suite_id")
    validate_page(page)
    validate_limit(limit, 200)
    test_type_code = resolve_test_type(test_type) if test_type else None
    perms = get_project_permissions()

    items, total = TestDefinition.list_for_suite(
        test_suite_id=suite_uuid,
        project_codes=perms.allowed_codes,
        table_name=table_name,
        test_type=test_type_code,
        test_active=test_active,
        page=page,
        limit=limit,
    )

    if not items:
        filters = []
        if table_name:
            filters.append(f"table={table_name}")
        if test_type:
            filters.append(f"type={test_type}")
        if test_active is not None:
            filters.append(f"active={test_active}")
        filter_str = f" (filters: {', '.join(filters)})" if filters else ""
        if page > 1:
            return f"No tests on page {page} (total: {total}){filter_str}."
        return f"No test definitions found for test suite `{test_suite_id}`{filter_str}."

    notes_counts = TestDefinitionNote.get_notes_count_by_ids([str(td.id) for td in items])

    headers = ["Test Type", "Table", "Column", "Active", "Severity", "Locked", "Manual", "Flagged", "Notes", "ID"]
    rows = []
    for td in items:
        note_ct = notes_counts.get(str(td.id), 0)
        rows.append(
            [
                td.display_name,
                td.table_name,
                td.column_name or None,
                "Yes" if td.test_active else "No",
                td.severity or td.default_severity or None,
                "Yes" if td.lock_refresh else "No",
                "No" if td.last_auto_gen_date else "Yes",
                "Yes" if td.flagged else "No",
                str(note_ct) if note_ct else None,
                str(td.id),
            ]
        )

    doc = MdDoc()
    doc.heading(1, f"Test Definitions for suite `{test_suite_id}`")
    doc.text(format_page_info(total, page, limit))
    doc.table(headers, rows, code=[1, 2, 9])
    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_test(test_definition_id: str) -> str:
    """Get full details of a test definition, including configuration, parameters, and last result.

    Args:
        test_definition_id: The UUID of the test definition.
    """
    def_uuid = parse_uuid(test_definition_id, "test_definition_id")
    perms = get_project_permissions()

    td = TestDefinition.get_for_project(def_uuid, perms.allowed_codes)
    if td is None:
        return f"Test definition `{test_definition_id}` not found."

    test_name = td.display_name

    doc = MdDoc()

    # Header
    if td.column_name:
        doc.heading(1, f"{test_name} on `{td.column_name}` in `{td.table_name}`")
    else:
        doc.heading(1, f"{test_name} on `{td.table_name}`")

    doc.field("ID", td.id, code=True)
    doc.field("Test Type", test_name)
    doc.field("Table", td.table_name, code=True)
    if td.column_name:
        doc.field("Column", td.column_name, code=True)
    doc.field("Schema", td.schema_name, code=True)
    if td.test_scope:
        doc.field("Scope", td.test_scope)
    if td.impact_dimension or td.default_impact_dimension:
        doc.field("Impact Dimension", td.impact_dimension or td.default_impact_dimension)
    if td.dq_dimension:
        doc.field("Quality Dimension", td.dq_dimension)

    # Configuration
    doc.heading(2, "Configuration")
    doc.field("Active", "Yes" if td.test_active else "No")
    severity = td.severity or (f"{td.default_severity} (test type default)" if td.default_severity else None)
    if severity:
        doc.field("Severity", severity)
    doc.field("Locked", "Yes" if td.lock_refresh else "No")
    if td.export_to_observability is None:
        from testgen.common.models.test_suite import TestSuite

        suite = TestSuite.get(td.test_suite_id)
        inherited = suite.export_to_observability if suite else None
        doc.field("Export to Observability", f"{'Yes' if inherited else 'No'} (inherited from suite)")
    else:
        doc.field("Export to Observability", "Yes" if td.export_to_observability else "No")

    # Review status
    notes = TestDefinitionNote.get_notes(def_uuid)
    flag_str = "Flagged" if td.flagged else "Not Flagged"
    note_str = f"{len(notes)} Notes" if notes else "No Notes"
    doc.field("Review", f"{flag_str}, {note_str}")

    # Origin and last update
    if td.last_manual_update and td.last_auto_gen_date:
        doc.field("Last Updated", f"{max(td.last_manual_update, td.last_auto_gen_date)} (auto-generated, edited)")
    elif td.last_manual_update:
        doc.field("Last Updated", f"{td.last_manual_update} (manual edit)")
    elif td.last_auto_gen_date:
        doc.field("Last Updated", f"{td.last_auto_gen_date} (auto-generated)")

    # Parameters (editable fields from test type metadata)
    _append_parameters_section(doc, td)

    # Custom SQL (only show when the test type declares it as an editable parameter)
    if "custom_query" in td.param_columns:
        doc.heading(2, "Custom SQL")
        if td.custom_query:
            doc.code_block(td.custom_query, language="sql")
        else:
            doc.text("_No custom SQL defined._")

    # Reference match (only fields listed in param_columns)
    _append_match_section(doc, td)

    # Last result
    results = TestResult.select_history(
        test_definition_id=def_uuid,
        project_codes=perms.allowed_codes,
        limit=1,
    )
    doc.heading(2, "Last Result")
    if results:
        r = results[0]
        doc.field("Date", r.test_time)
        doc.field("Status", r.status.value if r.status else None)
        if r.message:
            doc.field("Message", r.message)
    else:
        doc.text("_No results recorded for this test definition._")

    # Description
    description = td.test_description or td.default_test_description
    if description:
        doc.heading(2, "Description")
        doc.text(description)
    if td.usage_notes:
        doc.heading(2, "Usage Notes")
        doc.text(td.usage_notes)

    return doc.render()


@with_database_session
@mcp_permission("view")
def list_test_notes(test_definition_id: str) -> str:
    """List notes attached to a test definition, newest first.

    Args:
        test_definition_id: The UUID of the test definition.
    """
    def_uuid = parse_uuid(test_definition_id, "test_definition_id")
    perms = get_project_permissions()

    td = TestDefinition.get_for_project(def_uuid, perms.allowed_codes)
    if td is None:
        return f"Test definition `{test_definition_id}` not found."

    notes = TestDefinitionNote.get_notes(def_uuid)
    if not notes:
        return f"No notes for test definition `{test_definition_id}`."

    test_name = td.display_name

    doc = MdDoc()
    if td.column_name:
        doc.heading(1, f"Notes for {test_name} on `{td.column_name}` in `{td.table_name}`")
    else:
        doc.heading(1, f"Notes for {test_name} on `{td.table_name}`")

    doc.text(f"{len(notes)} note(s).")
    doc.table(
        headers=["Date", "Author", "Note", "Updated"],
        rows=[
            [n["created_at"], n["created_by"], n["detail"], n["updated_at"]]
            for n in notes
        ],
    )
    return doc.render()


def _append_parameters_section(doc: MdDoc, td: TestDefinitionSummary) -> None:
    """Build the editable parameters table from test type metadata.

    Always shows all parameters declared in param_columns, even when the
    value is empty — this tells the LLM/user which fields can be edited.
    """
    if not td.param_fields:
        return

    rows = []
    for column, prompt, _help in td.param_fields:
        value = getattr(td, column, None)
        rows.append([prompt, column, str(value) if value is not None else None])

    doc.heading(2, "Parameters")
    doc.table(["Parameter", "Field", "Value"], rows, code=[1])


def _append_match_section(doc: MdDoc, td: TestDefinitionSummary) -> None:
    """Append reference match section — shows all match fields declared in param_columns."""
    match_fields = [
        ("Match Schema", "match_schema_name", td.match_schema_name),
        ("Match Table", "match_table_name", td.match_table_name),
        ("Match Columns", "match_column_names", td.match_column_names),
        ("Match Subset Condition", "match_subset_condition", td.match_subset_condition),
        ("Match Grouping Columns", "match_groupby_names", td.match_groupby_names),
        ("Match Having Condition", "match_having_condition", td.match_having_condition),
    ]
    relevant = [(label, value) for label, col, value in match_fields if col in td.param_columns]
    if not relevant:
        return

    doc.heading(2, "Reference Match")
    for label, value in relevant:
        doc.field(label, value, code=bool(value))


@with_database_session
def list_test_types(
    scope: str | None = None,
    impact_dimension: str | None = None,
    quality_dimension: str | None = None,
) -> str:
    """List available test types with optional filtering.

    Args:
        scope: Filter by test scope ('column', 'table', 'referential', 'custom').
        impact_dimension: Filter by impact dimension ('Reliability', 'Conformance', 'Regularity', 'Usability').
        quality_dimension: Filter by quality dimension ('Accuracy', 'Completeness', 'Consistency', 'Recency', 'Timeliness', 'Uniqueness', 'Validity').
    """
    if scope and scope not in _VALID_SCOPES:
        valid = ", ".join(sorted(_VALID_SCOPES))
        raise MCPUserError(f"Invalid scope `{scope}`. Valid values: {valid}")
    if impact_dimension and impact_dimension not in _VALID_IMPACT_DIMENSIONS:
        valid = ", ".join(sorted(_VALID_IMPACT_DIMENSIONS))
        raise MCPUserError(f"Invalid impact_dimension `{impact_dimension}`. Valid values: {valid}")
    if quality_dimension and quality_dimension not in _VALID_DQ_DIMENSIONS:
        valid = ", ".join(sorted(_VALID_DQ_DIMENSIONS))
        raise MCPUserError(f"Invalid quality_dimension `{quality_dimension}`. Valid values: {valid}")

    clauses = [TestType.active == "Y"]
    if scope:
        clauses.append(TestType.test_scope == scope)
    if impact_dimension:
        clauses.append(TestType.impact_dimension == impact_dimension)
    if quality_dimension:
        clauses.append(TestType.dq_dimension == quality_dimension)

    test_types = TestType.select_where(*clauses)

    if not test_types:
        filters = []
        if scope:
            filters.append(f"scope={scope}")
        if quality_dimension:
            filters.append(f"dimension={quality_dimension}")
        filter_str = f" (filters: {', '.join(filters)})" if filters else ""
        return f"No test types found{filter_str}."

    filters_desc = []
    if scope:
        filters_desc.append(f"scope: {scope}")
    if quality_dimension:
        filters_desc.append(f"dimension: {quality_dimension}")
    filter_suffix = f" ({', '.join(filters_desc)})" if filters_desc else ""

    doc = MdDoc()
    doc.heading(1, "Test Types")
    doc.text(f"Showing {len(test_types)} test type(s){filter_suffix}.")
    doc.table(
        headers=["Test Type", "Impact Dimension", "Quality Dimension", "Scope", "Description"],
        rows=[
            [tt.test_name_short, tt.impact_dimension, tt.dq_dimension, tt.test_scope, tt.test_description]
            for tt in test_types
        ],
    )

    return doc.render()
