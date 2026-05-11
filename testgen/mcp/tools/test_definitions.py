from datetime import UTC, datetime
from enum import StrEnum
from typing import NoReturn

from sqlalchemy import update

from testgen.common.enums import ImpactDimension, QualityDimension
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import (
    InvalidTestDefinitionFields,
    TestDefinition,
    TestDefinitionNote,
    TestDefinitionSummary,
    TestType,
)
from testgen.common.models.test_result import TestResult
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    format_page_footer,
    format_page_info,
    parse_impact_dimension,
    parse_quality_dimension,
    parse_uuid,
    resolve_test_definition,
    resolve_test_suite,
    resolve_test_type,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc
from testgen.ui.services.database_service import fetch_from_target_db

_DOC_GROUP = DocGroup.DISCOVER

_VALID_SCOPES = {"column", "table", "referential", "custom"}


class BulkAction(StrEnum):
    ENABLE = "enable"
    DISABLE = "disable"


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

    doc = MdDoc()
    _append_td_summary(doc, td)

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


def _append_td_summary(doc: MdDoc, td: TestDefinitionSummary) -> None:
    """Render the identity, configuration, parameters, custom-SQL, and reference-match sections of a test definition."""
    test_name = td.display_name

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
    notes = TestDefinitionNote.get_notes(td.id)
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
    impact_dimension_enum: ImpactDimension | None = (
        parse_impact_dimension(impact_dimension) if impact_dimension else None
    )
    quality_dimension_enum: QualityDimension | None = (
        parse_quality_dimension(quality_dimension) if quality_dimension else None
    )

    clauses = [TestType.active == "Y"]
    if scope:
        clauses.append(TestType.test_scope == scope)
    if impact_dimension_enum is not None:
        clauses.append(TestType.impact_dimension == impact_dimension_enum)
    if quality_dimension_enum is not None:
        clauses.append(TestType.dq_dimension == quality_dimension_enum)

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


# ---------------------------------------------------------------------------
# Write tools (create / update / validate / bulk-update)
#
# All gated on ``edit`` permission. Atomic semantics on ``update_test`` —
# validation aggregates every field error before raising, so the LLM sees the
# full set in one response and the DB is never touched on a partial-error path.
# ---------------------------------------------------------------------------


def _raise_validation_errors(err: InvalidTestDefinitionFields, header: str) -> NoReturn:
    """Convert aggregated validation errors into a user-facing ``MCPUserError``."""
    bullets = "\n".join(f"- `{field}`: {reason}" for field, reason in err.errors.items())
    raise MCPUserError(f"{header}\n\n{bullets}") from err


@with_database_session
@mcp_permission("edit")
def create_test(
    test_suite_id: str,
    test_type: str,
    table_name: str,
    column_name: str | None = None,
    threshold_value: str | None = None,
    baseline_value: str | None = None,
    severity: str | None = None,
    custom_query: str | None = None,
    extra_params: dict | None = None,
) -> str:
    """Create a test in a test suite.

    Args:
        test_suite_id: UUID of the test suite.
        test_type: Test type name, e.g. ``Alpha Truncation`` or ``Custom Test``.
        table_name: Target table name. Case-sensitive.
        column_name: Required for column-scoped test types.
        threshold_value: Test threshold.
        baseline_value: Baseline reference.
        severity: ``Fail`` or ``Warning``. Omit to inherit the test type default.
        custom_query: SQL for tests that accept a custom query.
        extra_params: Additional test-type-specific parameters (e.g. ``window_days``,
            ``match_column_names``, ``lower_tolerance``). Use ``list_test_types`` or
            ``get_test`` on a similar test to discover supported names.
    """
    suite = resolve_test_suite(test_suite_id)
    tt_code = resolve_test_type(test_type)
    tt = TestType.get(tt_code)
    if tt is None:  # resolve_test_type already raised if the short name is unknown
        raise MCPUserError(f"Unknown test type: `{test_type}`.")

    table_group = TableGroup.get(suite.table_groups_id)
    if table_group is None:
        raise MCPUserError("Test suite is not associated with a table group.")

    td = TestDefinition(
        test_suite_id=suite.id,
        table_groups_id=table_group.id,
        test_type=tt_code,
        schema_name=table_group.table_group_schema,
        table_name=table_name,
        test_active=True,
        lock_refresh=False,
        last_manual_update=datetime.now(UTC),
    )
    explicit = {
        "column_name": column_name,
        "threshold_value": threshold_value,
        "baseline_value": baseline_value,
        "severity": severity,
        "custom_query": custom_query,
    }
    for key, value in explicit.items():
        if value is not None:
            setattr(td, key, value)

    if extra_params:
        accepted = td.editable_fields(tt)
        rejected = sorted(set(extra_params) - accepted)
        if rejected:
            raise MCPUserError(
                f"These `extra_params` keys are not editable for test type `{tt_code}`: "
                f"{', '.join(rejected)}."
            )
        conflicts = sorted(set(extra_params) & {k for k, v in explicit.items() if v is not None})
        if conflicts:
            raise MCPUserError(
                f"These fields were set both as named arguments and in `extra_params`: "
                f"{', '.join(conflicts)}. Pass each value only once."
            )
        for key, value in extra_params.items():
            setattr(td, key, value)

    try:
        td.validate(tt)
    except InvalidTestDefinitionFields as e:
        _raise_validation_errors(e, "Test definition creation rejected. No changes saved.")

    td.save()

    # The joined test-type metadata (param_fields, default_severity, dq_dimension, ...)
    # is only present on the Summary dataclass, so re-fetch for rendering.
    perms = get_project_permissions()
    summary = TestDefinition.get_for_project(td.id, perms.allowed_codes)

    doc = MdDoc()
    doc.text(f"**Created** in suite `{suite.test_suite}`.")
    _append_td_summary(doc, summary)
    return doc.render()


@with_database_session
@mcp_permission("edit")
def update_test(test_definition_id: str, fields: dict) -> str:
    """Update fields on an existing test. Atomic — no partial save.

    Args:
        test_definition_id: UUID of the test definition.
        fields: Mapping of field name to new value. Accepts the test type's parameter
            columns (use ``get_test`` to see the current values and supported fields)
            plus ``test_active``, ``severity``, ``lock_refresh``, ``flagged``.
    """
    td = resolve_test_definition(test_definition_id)
    tt = TestType.get(td.test_type)
    if tt is None:
        raise MCPUserError(f"Test type `{td.test_type}` not found for this test definition.")

    if not fields:
        raise MCPUserError("No fields supplied to update.")

    accepted = td.editable_fields(tt)
    rejected = sorted(set(fields) - accepted)
    if rejected:
        bullets = "\n".join(
            f"- `{key}`: not editable for test type `{tt.test_type}`" for key in rejected
        )
        raise MCPUserError(f"Update rejected. No changes saved.\n\n{bullets}")

    before: dict = {key: getattr(td, key, None) for key in fields}
    for key, value in fields.items():
        setattr(td, key, value)
    td.last_manual_update = datetime.now(UTC)

    try:
        td.validate(tt)
    except InvalidTestDefinitionFields as e:
        _raise_validation_errors(e, "Update rejected. No changes saved.")

    td.save()

    doc = MdDoc()
    doc.heading(1, f"Test definition `{td.id}` updated")
    rows = [[key, _format_diff(before[key]), _format_diff(fields[key])] for key in fields]
    doc.table(["Field", "Before", "After"], rows, code=[0])
    doc.text(f"{len(fields)} field(s) changed.")
    return doc.render()


def _format_diff(value: object) -> str | None:
    """Render a before/after cell, normalizing empty strings to ``None`` (NullIfEmptyString)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


@with_database_session
@mcp_permission("edit")
def validate_custom_test(test_suite_id: str, custom_sql: str) -> str:
    """Dry-run a custom test SQL query against the test suite's parent connection.

    Args:
        test_suite_id: UUID of the test suite whose connection the SQL runs against.
        custom_sql: SQL query to dry-run.
    """
    suite = resolve_test_suite(test_suite_id)
    connection = Connection.get_by_table_group(suite.table_groups_id)
    if connection is None:
        raise MCPUserError("No connection configured for this test suite's table group.")

    perms = get_project_permissions()
    can_view_pii = suite.project_code in perms.codes_allowed_to("view_pii")

    doc = MdDoc()
    doc.heading(1, "Custom test dry-run")

    try:
        rows = fetch_from_target_db(connection, custom_sql)
    except Exception as e:  # broad catch: the DB error message IS the user-facing signal
        doc.text(f"**SQL did not execute.** Query was not committed against `{connection.connection_name}`.")
        message = str(e.args[0]) if e.args else str(e)
        doc.text("**Error:**")
        doc.code_block(message)
        return doc.render()

    row_count = len(rows)
    flavor = connection.sql_flavor_code or connection.sql_flavor or "target database"
    doc.text(
        f"**SQL ran successfully** against `{connection.connection_name}` ({flavor})."
    )

    if row_count == 0:
        doc.text("**Would pass:** ✓ — query returned 0 error rows.")
        doc.text(
            "_If saved as a CUSTOM test, this would currently pass: the test fails when any "
            "error rows are returned, and there are none._"
        )
        return doc.render()

    doc.text(f"**Would fail:** ✗ — query returned {row_count} error row(s).")
    doc.heading(2, "Source data preview (first row)")
    first = rows[0]
    columns = list(first.keys())
    if can_view_pii:
        values = [first[c] for c in columns]
    else:
        values = ["[redacted]"] * len(columns)
    doc.table(columns, [values])
    doc.text(
        "_If saved as a CUSTOM test, this would currently fail because the SQL returned error "
        "rows. Refine the query if some of those rows are false positives._"
    )
    if not can_view_pii:
        doc.text(
            "_PII redacted: caller does not have `view_pii` on this project. Column names shown "
            "so the LLM can iterate on shape; row values are masked._"
        )
    return doc.render()


@with_database_session
@mcp_permission("edit")
def bulk_update_tests(
    test_suite_id: str,
    action: str,
    table_name: str | None = None,
    test_type: str | None = None,
) -> str:
    """Enable or disable tests in a suite in bulk.

    Args:
        test_suite_id: UUID of the test suite.
        action: ``enable`` or ``disable``.
        table_name: Optional table-name filter. Case-sensitive.
        test_type: Optional test type name (e.g. ``Alpha Truncation``).
    """
    try:
        bulk_action = BulkAction(action)
    except ValueError as err:
        valid = ", ".join(f"`{a.value}`" for a in BulkAction)
        raise MCPUserError(f"`action` must be one of: {valid}.") from err
    suite = resolve_test_suite(test_suite_id)
    tt_code = resolve_test_type(test_type) if test_type else None

    target = bulk_action is BulkAction.ENABLE
    values: dict = {"test_active": target}
    if target:
        # Mirrors set_status_attribute: clearing the status when re-enabling so failed
        # tests don't carry forward a stale "disabled because of X" marker.
        values["test_definition_status"] = None

    where_clauses = [TestDefinition.test_suite_id == suite.id]
    if table_name:
        where_clauses.append(TestDefinition.table_name == table_name)
    if tt_code:
        where_clauses.append(TestDefinition.test_type == tt_code)

    stmt = (
        update(TestDefinition)
        .where(*where_clauses)
        .values(**values)
        .returning(TestDefinition.id)
    )
    session = get_current_session()
    affected = session.execute(stmt).all()
    count = len(affected)

    verb = "Enabled" if target else "Disabled"
    filters = []
    if table_name:
        filters.append(f"table_name=`{table_name}`")
    if test_type:
        filters.append(f"test_type=`{test_type}`")
    filter_str = ", ".join(filters) if filters else "no filter"

    doc = MdDoc()
    if count == 0:
        doc.heading(1, "No tests matched")
        doc.text(
            f"No tests in suite `{suite.test_suite}` matched the filter ({filter_str}). Nothing changed."
        )
        return doc.render()

    doc.heading(1, f"{verb} {count} test(s) in suite `{suite.test_suite}`")
    doc.field("Filter", filter_str)
    return doc.render()
