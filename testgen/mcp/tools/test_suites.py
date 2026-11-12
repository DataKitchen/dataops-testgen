"""MCP write tools for test suites — create, update, and delete standard and contract (non-monitor) suites.

Monitor suites (``suite_type`` of ``monitor``) are managed exclusively through the dedicated
monitors surface. ``resolve_test_suite`` already filters them out, so an
``update_test_suite`` call against a monitor-suite ID surfaces the unified
``not found or not accessible`` error.
"""

from __future__ import annotations

import hashlib
from dataclasses import astuple, dataclass
from typing import Annotated, Any
from uuid import UUID

from mcp.server.fastmcp import Context
from pydantic import Field
from sqlalchemy.exc import IntegrityError

from testgen.commands.test_generation import ContractGenerationResult
from testgen.common import contract_creation, contract_document
from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.audit.test_suites import record_contract_created
from testgen.common.database.test_suite_service import (
    duplicate_name_message,
    is_duplicate_name_error,
    validate_test_suite_fields,
)
from testgen.common.enums import JOB_STATUS_LABEL, JobKey, JobStatus, SuiteType
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.test_definition import Severity
from testgen.common.models.test_suite import SuiteDeletionCounts, TestSuite
from testgen.common.odcs.servers import CustomServerReason
from testgen.mcp.confirmation import confirm_destructive_action
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
from testgen.mcp.workers import run_on_worker_thread

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
            description="Type of test suite to create. Accepts `Standard` or `Contract`. Defaults to `Standard`.",
        ),
    ] = "Standard",
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
            description="Optional default severity applied to tests that do not set their own. Accepts `Fail`, "
            "`Warning`, or `Log`.",
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
            raise MCPUserError("`table_names` applies to contracts only. No changes saved.")
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
    custom_server_note: str | None = None
    try:
        if parsed_suite_type is SuiteType.CONTRACT:
            connection = Connection.get(table_group.connection_id)
            created = contract_creation.create_contract(suite, table_group, connection, table_names)
        else:
            session = get_current_session()
            session.add(suite)
            # Flush so the autogenerated ``id`` is available for the rendered response.
            session.flush()
    except IntegrityError as err:
        _raise_if_duplicate_name(err, name)
        raise
    if parsed_suite_type is SuiteType.CONTRACT:
        record_contract_created(created.suite)
        if created.custom_server_reason is not None:
            custom_server_note = _custom_server_note(created.custom_server_reason, connection.sql_flavor_code)
        generation, generation_failed = created.generation, created.generation_failed
    else:
        record(AuditAction.TEST_SUITE_CREATED, suite)

    return _render_created_suite(
        suite,
        table_group_name=table_group.table_groups_name,
        generation=generation,
        generation_failed=generation_failed,
        custom_server_note=custom_server_note,
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
        Field(description="New default severity for tests that do not set their own. Accepts `Fail`, `Warning`, or `Log`."),
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

    name = suite.test_suite
    try:
        suite.save()
    except IntegrityError as err:
        _raise_if_duplicate_name(err, name)
        raise
    record(AuditAction.TEST_SUITE_UPDATED, suite)
    return doc.render()


def _raise_if_duplicate_name(err: IntegrityError, name: str) -> None:
    if is_duplicate_name_error(err):
        raise MCPUserError(f"{duplicate_name_message(name)} No changes saved.") from err


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


def _custom_server_note(reason: CustomServerReason, sql_flavor_code: str) -> str:
    if reason.server_type is None:
        cause = f"a `{format_flavor_label(sql_flavor_code)}` connection has no matching server type in the standard"
    else:
        fields = ", ".join(f"`{name}`" for name in reason.missing_fields)
        cause = f"the connection does not supply {fields}, which `{reason.server_type.value}` requires"
    return f"The contract's server entry uses the custom type, because {cause}."


def _render_created_suite(
    suite: TestSuite,
    *,
    table_group_name: str,
    generation: ContractGenerationResult | None = None,
    generation_failed: bool = False,
    custom_server_note: str | None = None,
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
    if custom_server_note:
        doc.text(custom_server_note)
    if generation_failed:
        doc.text(
            "The contract was created, but generating its tables failed. Run `generate_tests` on "
            f"`{suite.id}` to generate it."
        )
    if generation is not None:
        doc.field("Declared tables", ", ".join(f"`{name}`" for name in generation.tables_declared))
        doc.field("Tests besides schema conformance", generation.term_count)
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


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

_JOB_LABELS = {
    JobKey.run_tests: "test run",
    JobKey.run_test_generation: "test generation",
}

_COUNT_LABELS = {
    "test_definitions": "Test definitions",
    "notes": "Notes",
    "test_runs": "Test runs",
    "test_results": "Test results",
    "schedules": "Schedules",
    "notification_settings": "Notification settings",
    "contract_versions": "Frozen contract versions",
}


@dataclass(frozen=True, slots=True)
class _SuiteDeletePlan:
    suite_id: UUID
    label: str
    counts: SuiteDeletionCounts

    @property
    def operation_id(self) -> str:
        """Identifies the suite and the counts the user is shown, so a token does not confirm other counts."""
        digest = hashlib.sha256(repr(astuple(self.counts)).encode()).hexdigest()
        return f"delete_test_suite:{self.suite_id}:{digest}"


def _suite_label(suite: TestSuite) -> str:
    noun = "contract" if suite.suite_type == SuiteType.CONTRACT else "test suite"
    return f"{noun} `{suite.test_suite}`"


def _labelled_counts(counts: SuiteDeletionCounts) -> dict[str, int]:
    return {label: getattr(counts, field) for field, label in _COUNT_LABELS.items()}


def _refuse_while_a_job_names(suite: TestSuite) -> None:
    """Raise naming every queued or running job for the suite, which deleting it would also delete."""
    jobs = JobExecution.select_active_by_kwargs(
        project_code=suite.project_code, kwargs_match={"test_suite_id": str(suite.id)}
    )
    if jobs:
        listed = ", ".join(
            f"{_JOB_LABELS.get(job.job_key, job.job_key)} `{job.id}` ({JOB_STATUS_LABEL.get(job.status, job.status)})"
            for job in jobs
        )
        message = (
            f"Nothing was deleted. Jobs for {_suite_label(suite)} are queued or running: {listed}. "
            "Cancel them (a test run with `cancel_test_run`) or let them finish, then try again."
        )
        if any(job.status == JobStatus.CANCEL_REQUESTED for job in jobs):
            message += " A job whose cancellation was requested blocks the delete until the cancellation completes."
        raise MCPUserError(message)


@with_database_session
@mcp_permission("edit")
def _plan_suite_deletion(test_suite_id: str) -> _SuiteDeletePlan:
    """Resolve the suite, refuse while a job for it is in flight, and count what deleting it removes."""
    suite = resolve_test_suite(test_suite_id)
    _refuse_while_a_job_names(suite)
    return _SuiteDeletePlan(suite.id, _suite_label(suite), TestSuite.deletion_counts(suite.id))


@with_database_session
@mcp_permission("edit")
def _delete_planned_suite(plan: _SuiteDeletePlan, test_suite_id: str) -> str:
    """Delete the suite, provided it still holds what ``plan`` counted, and render what went."""
    suite = resolve_test_suite(test_suite_id)
    _refuse_while_a_job_names(suite)
    if TestSuite.deletion_counts(suite.id) != plan.counts:
        raise MCPUserError(
            f"What {plan.label} holds changed while the request waited for confirmation. Nothing was deleted. "
            "Call `delete_test_suite` again to confirm what it holds now."
        )
    record(AuditAction.TEST_SUITE_DELETED, suite)
    TestSuite.cascade_delete([str(suite.id)])

    doc = MdDoc()
    doc.heading(1, f"Deleted {plan.label}")
    for label, count in _labelled_counts(plan.counts).items():
        if count:
            doc.field(label, count)
    return doc.render()


async def delete_test_suite(
    ctx: Context,
    test_suite_id: Annotated[
        str, Field(description="UUID of the test suite to delete, e.g. from `list_test_suites`.")
    ],
    confirmation_token: Annotated[
        str | None,
        Field(
            description="Token from an earlier `delete_test_suite` call that asked for confirmation. Show the "
            "user what that call said it would delete, and pass the token, with the same `test_suite_id`, "
            "only after the user has explicitly agreed. Never pass it on your own judgment.",
        ),
    ] = None,
) -> str:
    """Delete a test suite with everything in it, once the user confirms.

    The user is shown what goes and must confirm before anything is removed: the suite's test
    definitions in every version and their notes, its test runs and results, its schedules,
    its notification settings, and, for a contract, its versions. Refused while a job for the
    suite is queued or running.
    """
    plan = await run_on_worker_thread(_plan_suite_deletion, test_suite_id)
    await confirm_destructive_action(
        ctx,
        operation_id=plan.operation_id,
        prompt=f"Delete {plan.label} and everything in it?",
        counts=_labelled_counts(plan.counts),
        confirmation_token=confirmation_token,
        scope=f"delete_test_suite:{plan.suite_id}",
    )
    return await run_on_worker_thread(_delete_planned_suite, plan, test_suite_id)
