from typing import Annotated

from pydantic import Field
from sqlalchemy import func

from testgen.common import contract_service
from testgen.common.contract_service import VerificationUnavailable
from testgen.common.enums import SuiteType
from testgen.common.generation_set_service import (
    CONTRACT_GENERATION_SET,
    DEFAULT_GENERATION_SET,
    available_generation_sets,
)
from testgen.common.models import with_database_session
from testgen.common.models.data_table import CatalogLevel, DataTable, parse_catalog_tags, table_cde
from testgen.common.models.project import Project
from testgen.common.models.suite_version import ContractState, SuiteVersion, VersionState, format_version
from testgen.common.models.test_run import run_verdict
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    MCP_SUITE_TYPES,
    DocGroup,
    build_contains_pattern,
    format_catalog_tags_cell,
    format_flavor_label,
    format_page_footer,
    format_page_info,
    format_semantic_table_type,
    parse_suite_type,
    require_filter_text,
    resolve_connection,
    resolve_table_group,
    resolve_test_suite,
    tag_filter_clauses,
    tag_filter_description,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc, format_datetime

_DOC_GROUP = DocGroup.DISCOVER


@with_database_session
@mcp_permission("catalog")
def get_data_inventory() -> str:
    """Get a structural inventory of the TestGen configuration.
    Covers every project, connection, table group, and test suite accessible to the
    authenticated user. This is the recommended starting point for understanding the
    data quality landscape. Returns a structured markdown overview.
    """
    from testgen.mcp.services.inventory_service import get_inventory

    perms = get_project_permissions()
    return get_inventory(
        project_codes=perms.allowed_codes,
        view_project_codes=perms.codes_allowed_to("view"),
        username=perms.username,
        name=perms.name,
        is_global_admin=perms.is_global_admin,
        roles_by_code=perms.memberships,
    )


@with_database_session
@mcp_permission("catalog")
def list_projects() -> str:
    """List all projects the authenticated user has access to.

    Returns project codes and names. Use these to scope queries to specific projects.
    """
    perms = get_project_permissions()
    projects = [p for p in Project.select_where() if perms.has_access(p.project_code)]

    if not projects:
        return "No projects found."

    doc = MdDoc()
    doc.heading(1, "Projects")
    for project in projects:
        doc.field(project.project_name, project.project_code, code=True)

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_project(
    project_code: Annotated[str, Field(description="The project code, e.g. from `list_projects`.")],
) -> str:
    """Get a project's configuration and configuration counts.

    Returns the project name, observability and data-retention settings, and counts
    of connections, table groups, test suites, test definitions, profiling runs, and
    test runs scoped to the project. Use this before configuration changes to confirm
    a project's current shape.
    """
    perms = get_project_permissions()
    perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))

    project = Project.get(project_code)
    summary = Project.get_summary(project_code)
    if project is None or summary is None:
        raise MCPResourceNotAccessible("Project", project_code)

    doc = MdDoc()
    doc.heading(1, f"Project `{project_code}`")
    doc.field("Name", project.project_name)
    doc.field("Connections", summary.connection_count)
    doc.field("Table groups", summary.table_group_count)
    suite_count = summary.test_suite_count + summary.contract_count
    contracts = f" ({summary.contract_count} contracts)" if summary.contract_count else ""
    doc.field("Test suites", f"{suite_count}{contracts}")
    doc.field("Test definitions", summary.test_definition_count)
    doc.field("Profiling runs", summary.profiling_run_count)
    doc.field("Test runs", summary.test_run_count)

    doc.heading(2, "Configuration")
    doc.field("Weighted data quality scoring", project.use_dq_score_weights)

    doc.heading(2, "Observability Integration")
    doc.field("Configured", summary.can_export_to_observability)
    if project.observability_api_url:
        doc.field("API URL", project.observability_api_url, code=True)

    doc.heading(2, "Data Retention")
    doc.field("Automatically delete old profiling and test history", project.data_retention_enabled)
    if project.data_retention_enabled and project.data_retention_days is not None:
        doc.field("Delete history older than (days)", project.data_retention_days)

    return doc.render()


@with_database_session
@mcp_permission("view")
def list_test_suites(
    project_code: Annotated[str, Field(description="The project code to list test suites for.")],
    suite_type: Annotated[
        str | None,
        Field(description="Optional suite type to narrow to: `Standard` or `Contract`. Omit to list both."),
    ] = None,
) -> str:
    """List a project's test suites, contracts included, with latest run statistics."""
    if not project_code:
        return "Missing required parameter `project_code`."

    perms = get_project_permissions()
    perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))

    suite_types = (parse_suite_type(suite_type),) if suite_type else MCP_SUITE_TYPES
    summaries = TestSuite.select_summary(project_code, suite_types=suite_types)

    if not summaries:
        return f"No test suites found for project `{project_code}`."

    contract_ids = [s.id for s in summaries if s.suite_type == SuiteType.CONTRACT]
    states = SuiteVersion.states_for(contract_ids) if contract_ids else {}

    doc = MdDoc()
    doc.heading(1, f"Test Suites for `{project_code}`")
    for s in summaries:
        doc.heading(2, f"{s.test_suite} (id: `{s.id}`)")
        if s.suite_type == SuiteType.CONTRACT:
            doc.field("Type", _contract_state_label(states.get(s.id)))
        doc.field("Connection", s.connection_name)
        doc.field("Table Group", s.table_groups_name)
        if s.test_suite_description:
            doc.field("Description", s.test_suite_description)
        doc.field("Test definitions", s.test_ct or 0)
        if s.generation_sets:
            doc.field("Generation sets", ", ".join(s.generation_sets))

        if s.latest_run_id:
            doc.field("Latest run", f"`{s.latest_run_id}` ({format_datetime(s.latest_run_start)})")
            results_summary = (
                f"{s.last_run_test_ct or 0} tests: "
                f"{s.last_run_passed_ct or 0} passed, "
                f"{s.last_run_failed_ct or 0} failed, "
                f"{s.last_run_warning_ct or 0} warnings, "
                f"{s.last_run_error_ct or 0} errors"
            )
            doc.field("Results", results_summary)
            if s.last_run_dismissed_ct:
                doc.field("Dismissed", s.last_run_dismissed_ct)
        elif s.suite_type == SuiteType.CONTRACT:
            doc.text("_No completed run counts as contract status. Preview runs are excluded._")
        else:
            doc.text("_No completed runs._")

    return doc.render()


def _contract_state_label(state: ContractState | None) -> str:
    parts = ["Contract"]
    if state and state.active:
        parts.append(format_version(state.active.version, VersionState.ACTIVE))
    if state and state.draft:
        parts.append(format_version(state.draft.version, VersionState.DRAFT))
    return " · ".join(parts)


@with_database_session
@mcp_permission("view")
def get_test_suite(
    test_suite_id: Annotated[str, Field(description="The test suite UUID, e.g. from `list_test_suites`.")],
) -> str:
    """Get a test suite's configuration and test-definition breakdown.
    Returns the suite's connection, table group, and default severity, along with a
    breakdown of how many test definitions it contains by type and how many are locked
    (excluded from regeneration). Use this before changing a suite's tests to understand
    what will be affected.
    """
    suite = resolve_test_suite(test_suite_id)
    # Defense in depth: resolve via perm-filtered helpers rather than `Model.get(...)`.
    # FK constraints guarantee same-project today; the resolvers are the established wrapper
    # for project-scoped lookups and keep us aligned if those guarantees ever change.
    connection = resolve_connection(suite.connection_id) if suite.connection_id else None
    table_group = resolve_table_group(str(suite.table_groups_id)) if suite.table_groups_id else None
    stats = TestSuite.test_definition_stats(suite.id)

    doc = MdDoc()
    doc.heading(1, f"Test Suite `{suite.test_suite}`")
    doc.field("ID", str(suite.id), code=True)
    doc.field("Project", suite.project_code, code=True)

    if connection is not None:
        doc.field(
            "Connection",
            f"{connection.connection_name} (`{connection.connection_id}`, {format_flavor_label(connection.sql_flavor_code)})",
        )
    if table_group is not None:
        doc.field(
            "Table group",
            f"{table_group.table_groups_name} (`{table_group.id}`)",
        )

    if suite.test_suite_description:
        doc.field("Description", suite.test_suite_description)
    doc.field("Default severity", suite.severity or "Inherit from test type")
    doc.field("Export to observability", suite.export_to_observability)
    doc.field("Automatically deactivate tests that fail validation", suite.deactivate_invalid_tests)
    default_set = CONTRACT_GENERATION_SET if suite.suite_type == SuiteType.CONTRACT else DEFAULT_GENERATION_SET
    doc.field("Generation sets", ", ".join(suite.generation_sets or []) or f"Not set, defaults to {default_set}")
    doc.field("Available generation sets", ", ".join(available_generation_sets(suite)))

    doc.field("Total tests", stats.total)
    doc.field("Locked tests", stats.locked)

    if stats.counts_by_type:
        doc.heading(2, "Tests by type")
        rows = [[type_label, count] for type_label, count in stats.counts_by_type.items()]
        doc.table(["Test", "Count"], rows)

    if suite.suite_type == SuiteType.CONTRACT:
        _render_contract_block(doc, suite)

    return doc.render()


def _render_contract_block(doc: MdDoc, suite: TestSuite) -> None:
    """Append the contract's active and draft versions and its latest verification verdict to ``doc``."""
    status = contract_service.contract_status(suite)
    active, draft = status.active, status.draft
    doc.heading(2, "Contract")
    if active:
        label = f' — "{active.label}"' if active.label else ""
        doc.field(
            "Active version",
            f"{format_version(active.version, VersionState.ACTIVE)}{label} (frozen {format_datetime(active.frozen_at)})",
        )
    else:
        doc.field("Active version", "None yet")
    doc.field("Draft", format_version(draft.version, VersionState.DRAFT) if draft else "None")
    if counted := status.counted_from:
        doc.field(
            "Tests counted from",
            format_version(counted.version, VersionState.DRAFT if draft else VersionState.ACTIVE),
        )

    if status.unavailable == VerificationUnavailable.nothing_frozen:
        doc.text("Verification unavailable: no version has been frozen yet, so runs of the draft are previews.")
        return
    active_label = format_version(active.version, VersionState.ACTIVE)
    if status.unavailable == VerificationUnavailable.not_run_since_frozen:
        doc.text(f"Verification unavailable: {active_label} has not run since it was frozen.")
        return
    incomplete = status.incomplete_run
    unfinished = f"(`{incomplete.job_execution_id}`) is {incomplete.status_label}." if incomplete else None
    summary = status.latest_verification
    if summary is None:
        doc.text(f"Verification unavailable: the latest run of {active_label} {unfinished}")
        return
    doc.field(
        "Latest verification",
        f"{run_verdict(summary).value} — run `{summary.job_execution_id}` "
        f"(started {format_datetime(summary.started_at)}); "
        f"{summary.test_ct or 0} tests: {summary.passed_ct or 0} passed, {summary.failed_ct or 0} failed, "
        f"{summary.warning_ct or 0} warnings, {summary.error_ct or 0} errors",
    )
    if unfinished:
        doc.text(f"A newer run of {active_label} {unfinished}")


@with_database_session
@mcp_permission("catalog")
def list_tables(
    table_group_id: Annotated[str, Field(description="The table group UUID.")],
    semantic_table_type: Annotated[
        str | None,
        Field(
            description="Matches tables whose semantic table type contains this text, ignoring case, e.g. `Summary`, "
            "`Cumulative`, `Window Transaction`. Use `%` as a wildcard within the text. A semantic table type combines "
            "a period, `Cumulative` (rows accumulate) or `Window` (older rows roll off), with a type: `Transaction`, "
            "`Entity`, `Summary`, `Bridge`, or `Domain`. Tables not yet profiled never match.",
        ),
    ] = None,
    cde: Annotated[
        bool | None,
        Field(description="When `true`, match tables flagged as a critical data element; when `false`, exclude them."),
    ] = None,
    data_source: Annotated[str | None, Field(description=tag_filter_description("data_source", CatalogLevel.TABLE))] = None,
    source_system: Annotated[str | None, Field(description=tag_filter_description("source_system", CatalogLevel.TABLE))] = None,
    source_process: Annotated[
        str | None, Field(description=tag_filter_description("source_process", CatalogLevel.TABLE))
    ] = None,
    business_domain: Annotated[
        str | None, Field(description=tag_filter_description("business_domain", CatalogLevel.TABLE))
    ] = None,
    stakeholder_group: Annotated[
        str | None, Field(description=tag_filter_description("stakeholder_group", CatalogLevel.TABLE))
    ] = None,
    transform_level: Annotated[
        str | None, Field(description=tag_filter_description("transform_level", CatalogLevel.TABLE))
    ] = None,
    aggregation_level: Annotated[
        str | None, Field(description=tag_filter_description("aggregation_level", CatalogLevel.TABLE))
    ] = None,
    data_product: Annotated[str | None, Field(description=tag_filter_description("data_product", CatalogLevel.TABLE))] = None,
    data_classification: Annotated[
        str | None, Field(description=tag_filter_description("data_classification", CatalogLevel.TABLE))
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of tables per page (default 200, max 500).")] = 200,
    page: Annotated[int, Field(description="Page number, starting from 1 (default 1).")] = 1,
) -> str:
    """List tables in a table group with their semantic table type and catalog tags.

    Filters combine with AND. Tag filters match the table's own value or, when it has none, the table group's.
    """
    validate_page(page)
    validate_limit(limit, 500)

    tg = resolve_table_group(table_group_id)

    tags = {
        "data_source": data_source,
        "source_system": source_system,
        "source_process": source_process,
        "business_domain": business_domain,
        "stakeholder_group": stakeholder_group,
        "transform_level": transform_level,
        "aggregation_level": aggregation_level,
        "data_product": data_product,
        "data_classification": data_classification,
    }
    clauses = tag_filter_clauses(tags, CatalogLevel.TABLE)
    if semantic_table_type is not None:
        require_filter_text("semantic_table_type", semantic_table_type)
        clauses.append(
            func.replace(DataTable.functional_table_type, "-", " ").ilike(
                build_contains_pattern(semantic_table_type.replace("-", " ")), escape="\\"
            )
        )
    if cde is not None:
        clauses.append(table_cde().is_(cde))

    tables, total = DataTable.list_for_table_group(*clauses, table_groups_id=tg.id, page=page, limit=limit)

    if not tables:
        if page > 1:
            return f"No tables on page {page} (total: {total})."
        if clauses:
            return "No tables match the supplied filters."
        return f"No tables found for table group `{table_group_id}`."

    doc = MdDoc()
    doc.heading(1, f"Tables in Table Group `{table_group_id}`")
    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    rows = []
    any_inherited = False
    for table in tables:
        catalog_tags = parse_catalog_tags(table.catalog_tags)
        any_inherited = any_inherited or any(tag.inherited_from for tag in catalog_tags)
        rows.append([
            table.table_name,
            format_semantic_table_type(table.functional_table_type),
            table.record_ct,
            "Y" if table.critical_data_element else "",
            format_catalog_tags_cell(catalog_tags),
        ])
    doc.table(["Table", "Semantic Table Type", "Records", "CDE", "Catalog Tags"], rows, code=[0])
    if any_inherited:
        doc.text("_A tag value marked (table group) is inherited from the table group._")

    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)

    return doc.render()
