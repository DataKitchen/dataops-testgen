"""MCP write tools for test suites — create and update regular and contract (non-monitor) suites.

Monitor suites (``suite_type`` of ``monitor``) are managed exclusively through the dedicated
monitors surface. ``resolve_test_suite`` already filters them out, so an
``update_test_suite`` call against a monitor-suite ID surfaces the unified
``not found or not accessible`` error.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field

from testgen.commands.test_generation import ContractGenerationResult, run_contract_generation
from testgen.common import contract_document, contract_service
from testgen.common.database.test_suite_service import validate_test_suite_fields
from testgen.common.enums import SuiteType
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.test_definition import Severity
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.servers import UnmappedFlavorError
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    SuiteTypeLabel,
    format_flavor_label,
    format_suite_type_label,
    parse_severity,
    parse_suite_type,
    raise_validation_error,
    render_diff_table,
    report_no_change,
    resolve_table_group,
    resolve_test_suite,
)
from testgen.mcp.tools.markdown import MdDoc

LOG = logging.getLogger("testgen")

_DOC_GROUP = DocGroup.MANAGE

# Free-text + component fields are stored as ``NullIfEmptyString`` columns: writing ``""``
# to one becomes ``NULL`` in the DB. Normalize on the way in so the diff-renderer doesn't
# flag a phantom change (``before=None`` → ``after=""``) on a value that the DB will read
# back as identical to before.
_OPTIONAL_TEXT_ATTRS = (
    "test_suite_description",
    "component_key",
    "component_type",
    "component_name",
)


_FIELD_NAMES = {"severity": "severity_default", "dq_score_exclude": "dq_score_exclude"}


def _empty_to_none(value: str | None) -> str | None:
    return value if value else None


@with_database_session
@mcp_permission("edit")
def create_test_suite(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `list_table_groups`.")],
    test_suite_name: Annotated[str, Field(description="Display name for the suite.")],
    *,
    suite_type: Annotated[
        str,
        Field(
            description="Kind of suite to create. Accepts `Regular` or `Contract`. Defaults to `Regular`. A "
            "contract is not yet visible to the other test suite tools (listing, updating, running).",
        ),
    ] = "Regular",
    table_names: Annotated[
        list[str] | None,
        Field(
            description="Contracts only. Tables of the table group the contract declares, e.g. from `list_tables`. "
            "Omit to create the contract with no tables declared.",
        ),
    ] = None,
    description: Annotated[str | None, Field(description="Optional free-text description.")] = None,
    severity_default: Annotated[
        str | None,
        Field(
            description="Optional default severity applied to tests that do not set their own. Accepts `Fail` or "
            "`Warning`.",
        ),
    ] = None,
    dq_score_exclude: Annotated[
        bool,
        Field(description="Whether to exclude this suite's results from data quality scoring. Defaults to False."),
    ] = False,
    deactivate_invalid_tests: Annotated[
        bool,
        Field(
            description="Whether tests that fail validation at the start of a run (a missing table or column, or a "
            "column type the test does not apply to) are deactivated automatically. Defaults to False.",
        ),
    ] = False,
    export_to_observability: Annotated[
        bool,
        Field(
            description="Whether to export test results to the configured DataOps Observability API. Defaults to "
            "False.",
        ),
    ] = False,
    component_key: Annotated[str | None, Field(description="Component identifier in DataOps Observability.")] = None,
    component_type: Annotated[
        str | None,
        Field(description="Component type in DataOps Observability (e.g. `dataset`). Defaults to `dataset`."),
    ] = "dataset",
    component_name: Annotated[str | None, Field(description="Component display name in DataOps Observability.")] = None,
) -> str:
    """Create a test suite under a table group.

    The new suite inherits the table group's project and connection.

    A contract created with ``table_names`` declares those tables and is generated right away:
    its metadata from the data catalog, a schema conformance test per table, and, for the tables
    profiling has results for, their tests and observed values. The response says how many tests it
    holds besides schema conformance, and names the tables profiling has no results for.
    """
    name = test_suite_name.strip() if test_suite_name else ""
    errors: list[str] = []
    parsed_severity: Severity | None = _parse_severity_field(severity_default, errors)
    parsed_suite_type: SuiteType | None = _parse_suite_type_field(suite_type, errors)
    if errors:
        raise_validation_error(errors, "Test suite creation rejected. No changes saved.")

    table_group = resolve_table_group(table_group_id)
    if table_names:
        if parsed_suite_type is not SuiteType.CONTRACT:
            raise MCPUserError("`table_names` applies only to contracts. No changes saved.")
        catalog_tables = set(contract_document.catalog_table_names(table_group.id))
        if unknown := [name for name in table_names if name not in catalog_tables]:
            raise MCPUserError(
                f"Table group `{table_group.table_groups_name}` has no tables named "
                f"{', '.join(f'`{name}`' for name in unknown)}. No changes saved."
            )

    suite = TestSuite(
        project_code=table_group.project_code,
        connection_id=table_group.connection_id,
        table_groups_id=table_group.id,
        test_suite=name,
        test_suite_description=_empty_to_none(description),
        severity=parsed_severity.value if parsed_severity is not None else None,
        suite_type=parsed_suite_type.value,
        dq_score_exclude=dq_score_exclude,
        deactivate_invalid_tests=deactivate_invalid_tests,
        export_to_observability=export_to_observability,
        component_key=_empty_to_none(component_key),
        component_type=_empty_to_none(component_type),
        component_name=_empty_to_none(component_name),
    )
    if errors := validate_test_suite_fields(suite, field_names=_FIELD_NAMES):
        raise_validation_error(errors, "Test suite creation rejected. No changes saved.")

    generation: ContractGenerationResult | None = None
    generation_failed = False
    session = get_current_session()
    session.add(suite)
    # Flush so the autogenerated ``id`` is available for the rendered response.
    session.flush()

    if parsed_suite_type is SuiteType.CONTRACT:
        connection = Connection.get(table_group.connection_id) if table_group.connection_id else None
        if connection is None:
            raise MCPUserError(
                f"Table group `{table_group.table_groups_name}` has no connection configured; "
                "a contract cannot be created without one."
            )
        try:
            contract_service.initialize_contract(suite, table_group, connection)
        except UnmappedFlavorError as e:
            flavor = format_flavor_label(connection.sql_flavor_code)
            raise MCPUserError(f"A contract cannot be created on a `{flavor}` connection yet.") from e
        except ValueError as e:
            raise MCPUserError(
                f"A contract cannot be created from connection `{connection.connection_name}`. {e}"
            ) from e
        if table_names:
            # Committed first so that a failed generation rolls back to the contract rather than past
            # it: the response reports it with its ID, and the caller does not retry into a duplicate.
            session.commit()
            try:
                generation = run_contract_generation(suite.id, table_names=list(dict.fromkeys(table_names)))
            except Exception:
                LOG.exception(f"Generating contract {suite.id} failed")
                session.rollback()
                generation_failed = True

    return _render_created_suite(
        suite, table_group_name=table_group.table_groups_name, generation=generation, generation_failed=generation_failed
    )


@with_database_session
@mcp_permission("edit")
def update_test_suite(
    test_suite_id: Annotated[str, Field(description="UUID of the test suite, e.g. from `list_test_suites`.")],
    *,
    test_suite_name: Annotated[str | None, Field(description="New display name.")] = None,
    description: Annotated[
        str | None,
        Field(description="New free-text description. Pass an empty string to clear."),
    ] = None,
    severity_default: Annotated[
        str | None,
        Field(description="New default severity for tests that do not set their own. Accepts `Fail` or `Warning`."),
    ] = None,
    dq_score_exclude: Annotated[
        bool | None,
        Field(description="Whether this suite's results are excluded from data quality scoring."),
    ] = None,
    deactivate_invalid_tests: Annotated[
        bool | None,
        Field(
            description="Whether tests that fail validation at the start of a run (a missing table or column, or a "
            "column type the test does not apply to) are deactivated automatically.",
        ),
    ] = None,
    export_to_observability: Annotated[
        bool | None,
        Field(description="Whether test results are exported to the configured DataOps Observability API."),
    ] = None,
    component_key: Annotated[
        str | None,
        Field(description="Component identifier in DataOps Observability. Pass an empty string to clear."),
    ] = None,
    component_type: Annotated[
        str | None,
        Field(description="Component type in DataOps Observability (e.g. `dataset`). Pass an empty string to clear."),
    ] = None,
    component_name: Annotated[
        str | None,
        Field(description="Component display name in DataOps Observability. Pass an empty string to clear."),
    ] = None,
) -> str:
    """Update fields on a test suite.
    Atomic — nothing is saved unless every supplied value is valid.
    """
    supplied = {
        "test_suite_name": test_suite_name,
        "description": description,
        "severity_default": severity_default,
        "dq_score_exclude": dq_score_exclude,
        "deactivate_invalid_tests": deactivate_invalid_tests,
        "export_to_observability": export_to_observability,
        "component_key": component_key,
        "component_type": component_type,
        "component_name": component_name,
    }
    if all(value is None for value in supplied.values()):
        raise MCPUserError("No fields supplied to update.")

    suite = resolve_test_suite(test_suite_id)

    # Validate every supplied field first; surface all errors at once.
    errors: list[str] = []
    updates: dict[str, Any] = {}

    if test_suite_name is not None:
        updates["test_suite"] = test_suite_name.strip()

    if description is not None:
        updates["test_suite_description"] = _empty_to_none(description)

    if severity_default is not None:
        parsed = _parse_severity_field(severity_default, errors)
        if parsed is not None:
            updates["severity"] = parsed.value

    if dq_score_exclude is not None:
        updates["dq_score_exclude"] = dq_score_exclude
    if deactivate_invalid_tests is not None:
        updates["deactivate_invalid_tests"] = deactivate_invalid_tests
    if export_to_observability is not None:
        updates["export_to_observability"] = export_to_observability
    if component_key is not None:
        updates["component_key"] = _empty_to_none(component_key)
    if component_type is not None:
        updates["component_type"] = _empty_to_none(component_type)
    if component_name is not None:
        updates["component_name"] = _empty_to_none(component_name)

    # Diff scoped to the attributes actually touched by this call.
    before = {attr: getattr(suite, attr, None) for attr in updates}
    for attr, value in updates.items():
        setattr(suite, attr, value)
    after = {attr: getattr(suite, attr, None) for attr in updates}

    errors.extend(validate_test_suite_fields(suite, field_names=_FIELD_NAMES))
    if errors:
        raise_validation_error(errors, "Update rejected. No changes saved.")

    doc = MdDoc()
    doc.heading(1, f"Test Suite `{suite.test_suite}` updated")
    doc.field("ID", str(suite.id), code=True)

    rendered = render_diff_table(doc, before, after, attrs=_DIFF_ORDER, labels=_DIFF_LABELS)
    if not rendered:
        return report_no_change(doc)

    suite.save()
    return doc.render()


def _parse_severity_field(value: str | None, errors: list[str]) -> Severity | None:
    """Validate a ``severity_default`` arg; append a field-scoped bullet on failure."""
    if value is None:
        return None
    try:
        return parse_severity(value)
    except MCPUserError:
        valid = ", ".join(s.value for s in Severity)
        errors.append(f"severity_default: must be one of {valid} (got `{value}`).")
        return None


def _parse_suite_type_field(value: str, errors: list[str]) -> SuiteType | None:
    """Validate a ``suite_type`` arg; append a field-scoped bullet on failure."""
    try:
        return parse_suite_type(value)
    except MCPUserError:
        valid = ", ".join(t.value for t in SuiteTypeLabel)
        errors.append(f"suite_type: must be one of {valid} (got `{value}`).")
        return None


def _render_created_suite(
    suite: TestSuite,
    *,
    table_group_name: str,
    generation: ContractGenerationResult | None = None,
    generation_failed: bool = False,
) -> str:
    doc = MdDoc()
    doc.heading(1, f"Test Suite `{suite.test_suite}` created")
    doc.field("ID", str(suite.id), code=True)
    doc.field("Type", format_suite_type_label(suite.suite_type))
    doc.field("Project", suite.project_code, code=True)
    doc.field("Table Group", f"{table_group_name} (`{suite.table_groups_id}`)")
    if suite.test_suite_description:
        doc.field("Description", suite.test_suite_description)
    if suite.severity:
        doc.field("Default severity", suite.severity)
    doc.field("Exclude from quality scoring", suite.dq_score_exclude)
    doc.field("Automatically deactivate tests that fail validation", suite.deactivate_invalid_tests)
    doc.field("Export to Observability", suite.export_to_observability)
    if suite.component_key:
        doc.field("Component key", suite.component_key)
    if suite.component_type:
        doc.field("Component type", suite.component_type)
    if suite.component_name:
        doc.field("Component name", suite.component_name)
    if generation_failed:
        doc.text(
            "The contract was created, but generating its tables failed. Run `generate_tests` on "
            f"`{suite.id}` to generate it."
        )
    if generation is not None:
        doc.field("Declared tables", ", ".join(f"`{name}`" for name in generation.tables_declared))
        doc.field("Tests", generation.term_count)
        if generation.tables_not_in_catalog:
            doc.text(
                "The data catalog holds no columns for "
                f"{', '.join(f'`{name}`' for name in generation.tables_not_in_catalog)}, so their schema is empty."
            )
        if not_profiled := [
            name for name in generation.tables_not_profiled if name not in generation.tables_not_in_catalog
        ]:
            doc.text(
                f"Table group `{table_group_name}` has no profiling results for "
                f"{', '.join(f'`{name}`' for name in not_profiled)}, so their metadata was "
                "generated from the data catalog alone and no tests were generated for them besides schema "
                "conformance. Run profiling with `run_profiling`, then `generate_tests` on the contract."
            )
    return doc.render()


# Order drives the diff-table rendering. Mirrors the update_test_suite arg order:
# observability + components grouped together, dq_score_exclude separate.
_DIFF_ORDER: tuple[str, ...] = (
    "test_suite",
    "test_suite_description",
    "severity",
    "dq_score_exclude",
    "deactivate_invalid_tests",
    "export_to_observability",
    "component_key",
    "component_type",
    "component_name",
)

_DIFF_LABELS: dict[str, str] = {
    "test_suite": "Name",
    "test_suite_description": "Description",
    "severity": "Default severity",
    "dq_score_exclude": "Exclude from quality scoring",
    "deactivate_invalid_tests": "Automatically deactivate tests that fail validation",
    "export_to_observability": "Export to Observability",
    "component_key": "Component key",
    "component_type": "Component type",
    "component_name": "Component name",
}
