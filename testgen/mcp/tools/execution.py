"""MCP tools for triggering and canceling TestGen jobs."""

from typing import Annotated, Any

from pydantic import Field
from sqlalchemy import select

from testgen.commands.test_generation import (
    parse_regeneration_groups,
    resolve_generation_profile_run,
    unprofiled_regeneration_note,
)
from testgen.common import contract_service, query_variables, run_overrides
from testgen.common.audit.runs import RunOperation
from testgen.common.database.table_group_service import unsupported_schema_override
from testgen.common.enums import JOB_STATUS_LABEL, JobKey, JobSource, RegenerationGroup, SuiteType
from testgen.common.generation_set_service import resolve_generation_sets
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.job_execution import EXTERNAL_URL_MAX_LENGTH, JobExecution, validate_caller_metadata
from testgen.common.models.suite_version import VersionState, format_version
from testgen.common.models.table_group import TableGroup, validate_schema_name
from testgen.common.run_service import launch_run, request_run_transition
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    match_enum,
    not_a_contract_error,
    parse_uuid,
    resolve_table_group,
    resolve_test_suite,
    unknown_version_error,
)

_DOC_GROUP = DocGroup.TRIGGER
from testgen.mcp.tools.markdown import MdDoc


@with_database_session
@mcp_permission("edit")
def run_tests(
    test_suite_id: Annotated[str, Field(description="UUID of the test suite to run, e.g. from ``list_test_suites``.")],
    schema_name: Annotated[str | None, Field(description=run_overrides.SCHEMA_NAME)] = None,
    table_names: Annotated[dict[str, str] | None, Field(description=run_overrides.TABLE_NAMES)] = None,
    match_schema_name: Annotated[str | None, Field(description=run_overrides.MATCH_SCHEMA_NAME)] = None,
    match_table_names: Annotated[
        dict[str, str] | None, Field(description=run_overrides.MATCH_TABLE_NAMES)
    ] = None,
    variables: Annotated[dict[str, str] | None, Field(description=query_variables.VARIABLES)] = None,
    external_url: Annotated[
        str | None,
        Field(
            description="Link back to whatever triggered this run, shown on the test results page.",
            max_length=EXTERNAL_URL_MAX_LENGTH,
        ),
    ] = None,
    metadata: Annotated[
        dict | None,
        Field(
            description="JSON object describing what triggered this run, up to 50 top-level keys and 10,240 "
            "bytes. Stored with the run and shown on the test results page.",
        ),
    ] = None,
    version: Annotated[
        int | None,
        Field(
            description="Contract version number to run, e.g. from ``list_contract_versions``. Defaults to the "
            "version in force, or the draft when none is frozen yet. Contracts only.",
        ),
    ] = None,
) -> str:
    """Submit a test run for a test suite. Returns immediately with a job_execution_id;
    use ``list_test_runs`` to track status.
    """
    suite = resolve_test_suite(test_suite_id)
    kwargs: dict[str, Any] = {"test_suite_id": str(suite.id)}
    for field, value in (("schema_name", schema_name), ("match_schema_name", match_schema_name)):
        if value:
            if error := validate_schema_name(value):
                raise MCPUserError(f"{field} {error}.")
            kwargs[field] = value
    for field, value in (("table_names", table_names), ("match_table_names", match_table_names)):
        if value:
            if error := run_overrides.validate_table_name_map(value):
                raise MCPUserError(f"{field}: {error}")
            kwargs[field] = value
    if variables:
        if error := query_variables.validate_values(variables):
            raise MCPUserError(error)
        kwargs["variables"] = variables
    if refusal := unsupported_schema_override(
        suite.table_groups_id, schema_name=schema_name, match_schema_name=match_schema_name
    ):
        raise MCPUserError(refusal)
    if error := validate_caller_metadata(metadata):
        raise MCPUserError(f"metadata {error}.")

    try:
        target = contract_service.run_target(suite, version)
    except contract_service.NotAContractError as error:
        raise not_a_contract_error(suite) from error
    except contract_service.UnknownVersionError as error:
        raise unknown_version_error(error) from error
    except contract_service.NoActiveTestsError as error:
        raise MCPUserError(
            f"{format_version(error.version.version, error.state)} of contract `{suite.test_suite}` "
            "has no active tests to run."
        ) from error
    version_label = None
    note = None
    if target is not None:
        version_label = format_version(target.version.version, target.state)
        kwargs["version_id"] = str(target.version.id)
        note = target.note
    job = launch_run(
        job_key=JobKey.run_tests,
        kwargs=kwargs,
        source=JobSource.mcp,
        project_code=suite.project_code,
        external_url=external_url,
        caller_metadata=metadata,
    )
    return _render_submission(
        "Test run", suite.test_suite, "Test suite", job, "list_test_runs", version=version_label, note=note
    ).render()


@with_database_session
@mcp_permission("edit")
def run_profiling(
    table_group_id: Annotated[
        str,
        Field(description="UUID of the table group to profile, e.g. from ``get_data_inventory``."),
    ],
) -> str:
    """Submit a profiling run for a table group.
    Returns immediately with a job_execution_id; use ``list_profiling_summaries`` to
    track status.
    """
    table_group = resolve_table_group(table_group_id)
    job = launch_run(
        job_key=JobKey.run_profile,
        kwargs={"table_group_id": str(table_group.id)},
        source=JobSource.mcp,
        project_code=table_group.project_code,
    )
    return _render_submission(
        "Profiling run", table_group.table_groups_name, "Table group", job, "list_profiling_summaries"
    ).render()


@with_database_session
@mcp_permission("edit")
def generate_tests(
    test_suite_id: Annotated[
        str,
        Field(description="UUID of the test suite to generate tests for, e.g. from ``list_test_suites``."),
    ],
    generation_sets: Annotated[
        list[str] | None,
        Field(description="Generation set names, e.g. from ``testgen://generation-sets``."),
    ] = None,
    regenerate: Annotated[
        list[str] | None,
        Field(description=(
            "Contracts only. What to regenerate; omit to refresh everything. `tests`: tests from the latest "
            "profiling, locked tests kept. `profiling`: functional types, keys, formats, and profiled values. "
            "`catalog`: catalog metadata (descriptions, tags, classification, and the critical data element, "
            "PII, and excluded data element flags) from the data catalog. A regenerated group replaces "
            "edits made to its fields in the contract. Columns and their types are always refreshed."
        )),
    ] = None,
) -> str:
    """Submit a test-generation job for a test suite, including a contract.
    Auto-creates test definitions from the latest profiling results for the table group;
    locked and manually created test definitions are preserved. Returns immediately with
    a job_execution_id.

    Generation sets scope which test types are created. Omit them to use the test suite's stored
    generation sets. Read ``testgen://generation-sets`` for the available sets and the test types
    each one covers. Test types outside the selected sets are deleted unless they are locked.

    A contract generates its tests and metadata (``get_contract_metadata``) into its draft. Its sets
    default to ``Contract``, which only a contract can use. It covers the declared tables, or every
    table when none are declared. Before its table group is profiled,
    only the catalog metadata and schema conformance tests are written.

    Value hash test types (Table Comparison set) need a profiling run with
    ``profile_table_comparison`` on (see ``get_table_group``).
    """
    suite = resolve_test_suite(test_suite_id)
    if regenerate is not None and suite.suite_type != SuiteType.CONTRACT:
        raise MCPUserError("`regenerate` applies to contracts only. Omit it for a test suite.")
    try:
        resolved_sets = resolve_generation_sets(suite, generation_sets)
    except ValueError as error:
        raise MCPUserError(str(error)) from error
    note = None
    groups: list[RegenerationGroup] = []
    if suite.suite_type == SuiteType.CONTRACT:
        table_group = TableGroup.get(suite.table_groups_id)
        profiled = resolve_generation_profile_run(table_group) is not None
        try:
            requested = (
                list(RegenerationGroup)
                if regenerate is None
                else [match_enum(value, RegenerationGroup) or value for value in regenerate]
            )
            groups = parse_regeneration_groups(requested, has_profiling_run=profiled)
        except ValueError as error:
            raise MCPUserError(str(error)) from error
        if not profiled and (skipped := unprofiled_regeneration_note(table_group.table_groups_name, groups)):
            note = f"{skipped} Run profiling with `run_profiling`, then generate again."

    version_label = None
    if suite.suite_type == SuiteType.CONTRACT:
        version_label = format_version(contract_service.generation_destination(suite), VersionState.DRAFT)

    job = JobExecution.submit(
        job_key=JobKey.run_test_generation,
        kwargs={
            "test_suite_id": str(suite.id),
            "generation_sets": resolved_sets,
            **({"regenerate": [str(group) for group in groups]} if groups else {}),
        },
        source=JobSource.mcp,
        project_code=suite.project_code,
    )
    return _render_submission(
        "Test generation",
        suite.test_suite,
        "Contract" if suite.suite_type == SuiteType.CONTRACT else "Test suite",
        job,
        "list_tests",
        poll_hint="to verify the new definitions appear",
        version=version_label,
        regenerate=groups,
        note=note,
    ).render()


@with_database_session
@mcp_permission("edit")
def cancel_test_run(
    job_execution_id: Annotated[str, Field(description="UUID of a test run, e.g. from ``list_test_runs``.")],
) -> str:
    """Request cancellation of a queued or running test run."""
    job = _resolve_job_execution(job_execution_id, JobKey.run_tests, "Test run")
    return _render_cancel(job, "Test run", "list_test_runs")


@with_database_session
@mcp_permission("edit")
def cancel_profiling_run(
    job_execution_id: Annotated[
        str,
        Field(description="UUID of a profiling run, e.g. from ``list_profiling_summaries``."),
    ],
) -> str:
    """Request cancellation of a profiling run that has not finished."""
    job = _resolve_job_execution(job_execution_id, JobKey.run_profile, "Profiling run")
    return _render_cancel(job, "Profiling run", "list_profiling_summaries")


def _resolve_job_execution(job_execution_id: str, expected_job_key: JobKey, kind: str) -> JobExecution:
    """Resolve a user-submitted job by ID + expected job_key, collapsing missing-or-inaccessible
    into one error path. Each MCP tool pins ``expected_job_key`` to a public kind, so the
    job_key match alone restricts the lookup to externally-visible jobs.
    """
    job_uuid = parse_uuid(job_execution_id, "job_execution_id")
    perms = get_project_permissions()
    job = get_current_session().scalars(
        select(JobExecution).where(
            JobExecution.id == job_uuid,
            JobExecution.job_key == expected_job_key,
            JobExecution.project_code.in_(perms.allowed_codes),
        )
    ).first()
    if job is None:
        raise MCPResourceNotAccessible(kind, job_execution_id)
    return job


def _render_submission(
    kind: str,
    scope_name: str,
    scope_label: str,
    job: JobExecution,
    poll_tool: str,
    poll_hint: str = "to track status",
    version: str | None = None,
    regenerate: list[RegenerationGroup] | None = None,
    note: str | None = None,
) -> MdDoc:
    doc = MdDoc()
    doc.heading(1, f"{kind} submitted for `{scope_name}`")
    doc.field(kind.title(), job.id, code=True)
    doc.field(scope_label, scope_name)
    doc.field("Status", "Pending")
    if version:
        doc.field("Version", version)
    if regenerate:
        doc.field("Regenerate", ", ".join(f"`{group}`" for group in regenerate))
    if note:
        doc.text(note)
    doc.text(f"Use `{poll_tool}` {poll_hint}.")
    return doc


def _render_cancel(job: JobExecution, kind: str, poll_tool: str) -> str:
    if not request_run_transition(job, RunOperation.CANCELED):
        status_label = JOB_STATUS_LABEL.get(job.status, job.status)
        raise MCPUserError(
            f"Cannot cancel — current status is {status_label}. Only a job that has not finished can be canceled."
        )
    doc = MdDoc()
    doc.heading(1, f"{kind} cancellation requested")
    doc.field(kind.title(), job.id, code=True)
    doc.field("Status", JOB_STATUS_LABEL.get(job.status, job.status))
    doc.text(f"Use `{poll_tool}` to confirm cancellation.")
    return doc.render()
