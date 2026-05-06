from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import func

from testgen.common.models import with_database_session
from testgen.common.models.hygiene_issue import Disposition, HygieneIssue, HygieneIssueType, IssueLikelihood, PiiRisk
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.table_group import TableGroup
from testgen.common.pii_masking import PII_REDACTED
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    format_disposition,
    format_page_footer,
    format_page_info,
    parse_disposition,
    parse_impact_dimension,
    parse_issue_likelihood_list,
    parse_pii_risk_list,
    parse_quality_dimension,
    parse_since_arg,
    parse_uuid,
    resolve_issue_type,
    resolve_table_group,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.BROWSE_PROFILING


def _redact_detail(row, view_pii_codes: set[str]) -> str:
    """Return the row's detail, redacted if the type is redactable, the column is PII,
    and the caller lacks `view_pii` on the row's project. Mirrors `mask_hygiene_detail`.
    """
    if row.detail_redactable and row.pii_flag and row.project_code not in view_pii_codes:
        return PII_REDACTED
    return row.detail


def _build_likelihood_clause(
    issue_likelihood: list[IssueLikelihood] | None,
    pii_risk: list[PiiRisk] | None,
) -> ColumnElement[bool] | None:
    """Construct the WHERE clause for the likelihood / pii_risk filter pair.

    `issue_likelihood` matches `HygieneIssueType.likelihood` directly, so PII rows
    (likelihood = "Potential PII") are excluded automatically. `pii_risk` matches
    only PII rows by also requiring `likelihood == "Potential PII"`. Providing one
    of the two filters therefore auto-excludes the other category.
    """
    likelihood_clause = HygieneIssueType.likelihood.in_(issue_likelihood) if issue_likelihood else None
    pii_clause = (
        and_(HygieneIssueType.likelihood == IssueLikelihood.POTENTIAL_PII, HygieneIssue.priority.in_(pii_risk))
        if pii_risk
        else None
    )
    if likelihood_clause is None:
        return pii_clause
    if pii_clause is None:
        return likelihood_clause
    return or_(likelihood_clause, pii_clause)


def _resolve_profile_run_je_id(
    *,
    job_execution_id: str | None,
    table_group_id: str | None,
) -> UUID:
    """Resolve the scope to the ``job_execution_id`` of a single profiling run.

    Mutual-exclusion + at-least-one validation done by caller. Collapses missing runs
    and inaccessible table groups into ``MCPResourceNotAccessible``.
    """
    if table_group_id:
        tg = resolve_table_group(table_group_id)
        je_uuid = ProfilingRun.get_latest_complete_je_id_for_table_group(tg.id)
        if je_uuid is None:
            raise MCPUserError(f"No completed profiling runs found for table group `{table_group_id}`.")
        return je_uuid

    job_uuid = parse_uuid(job_execution_id, "job_execution_id")
    run = ProfilingRun.get_by_id_or_job(job_uuid)
    perms = get_project_permissions()
    tg = TableGroup.get(run.table_groups_id) if run else None
    if run is None or tg is None or not perms.has_access(tg.project_code):
        raise MCPResourceNotAccessible("Profiling run", job_execution_id)
    return run.job_execution_id


@with_database_session
@mcp_permission("view")
def list_hygiene_issues(
    *,
    job_execution_id: str | None = None,
    table_group_id: str | None = None,
    table_name: str | None = None,
    column_name: str | None = None,
    impact_dimension: str | None = None,
    quality_dimension: str | None = None,
    disposition: str | None = "Confirmed",
    issue_likelihood: list[str] | None = None,
    pii_risk: list[str] | None = None,
    issue_type: str | None = None,
    limit: int = 50,
    page: int = 1,
) -> str:
    """List hygiene issues for a profiling run.

    Provide either ``job_execution_id`` for a specific run, or ``table_group_id`` to list
    the issues from its latest profiling run.

    Args:
        job_execution_id: UUID of a profiling run, e.g. from ``list_profiling_summaries``.
        table_group_id: UUID of a table group. Resolves to the latest completed profiling run.
            Mutually exclusive with ``job_execution_id``.
        table_name: Filter by table name (exact match).
        column_name: Filter by column name (exact match).
        impact_dimension: Filter by impact dimension ('Reliability', 'Conformance',
            'Regularity', 'Usability').
        quality_dimension: Filter by data quality dimension ('Accuracy', 'Completeness',
            'Consistency', 'Recency', 'Timeliness', 'Uniqueness', 'Validity').
        disposition: Filter by disposition. Defaults to 'Confirmed'.
            Valid values: 'Confirmed', 'Dismissed', 'Muted'.
        issue_likelihood: Filter by issue likelihood. Values: 'Definite', 'Likely', 'Possible'.
            Providing this filter auto-excludes PII issues; combine with ``pii_risk`` to include both.
        pii_risk: Filter by PII risk level. Values: 'High', 'Moderate'.
            Providing this filter auto-excludes regular issues.
        issue_type: Filter by hygiene issue type (e.g. 'Similar Values Match When Standardized').
            See ``testgen://hygiene-issue-types`` for the full list.
        limit: Maximum number of issues per page (default 50, max 200).
        page: Page number, starting from 1 (default 1).
    """
    if job_execution_id and table_group_id:
        raise MCPUserError("Pass either `job_execution_id` or `table_group_id`, not both.")
    if not job_execution_id and not table_group_id:
        raise MCPUserError("Provide either `job_execution_id` or `table_group_id`.")
    validate_page(page)
    validate_limit(limit, 200)

    perms = get_project_permissions()
    run_je_id = _resolve_profile_run_je_id(
        job_execution_id=job_execution_id,
        table_group_id=table_group_id,
    )

    issue_likelihood = parse_issue_likelihood_list(issue_likelihood) if issue_likelihood else None
    pii_risk = parse_pii_risk_list(pii_risk) if pii_risk else None

    clauses = [HygieneIssue.project_code.in_(perms.allowed_codes)]
    disposition_value = parse_disposition(disposition or "Confirmed")
    clauses.append(func.coalesce(HygieneIssue.disposition, Disposition.CONFIRMED) == disposition_value)
    if table_name:
        clauses.append(HygieneIssue.table_name == table_name)
    if column_name:
        clauses.append(HygieneIssue.column_name == column_name)
    if impact_dimension:
        clauses.append(HygieneIssue.impact_dimension == parse_impact_dimension(impact_dimension))
    if quality_dimension:
        clauses.append(HygieneIssueType.dq_dimension == parse_quality_dimension(quality_dimension))
    if issue_type:
        clauses.append(HygieneIssue.type_id == resolve_issue_type(issue_type))
    likelihood_clause = _build_likelihood_clause(issue_likelihood, pii_risk)
    if likelihood_clause is not None:
        clauses.append(likelihood_clause)

    rows, total = HygieneIssue.list_for_run(run_je_id, *clauses, page=page, limit=limit)

    doc = MdDoc()
    doc.heading(1, f"Hygiene Issues for profiling run `{run_je_id}`")
    if not rows:
        doc.text("_No hygiene issues match the supplied filters._")
        return doc.render()
    if info := format_page_info(total, page, limit):
        doc.text(info)

    view_pii_codes = set(perms.codes_allowed_to("view_pii"))
    for r in rows:
        location = f"`{r.column_name}` in `{r.table_name}`" if r.column_name else f"`{r.table_name}`"
        doc.heading(2, f"[{r.priority or 'Unknown'}] {r.issue_type_name} on {location}")
        doc.field("Issue ID", r.id, code=True)
        doc.field("Issue Type", r.issue_type_name)
        if r.impact_dimension:
            doc.field("Impact Dimension", r.impact_dimension)
        if r.dq_dimension:
            doc.field("Quality Dimension", r.dq_dimension)
        doc.field("Disposition", format_disposition(r.disposition))
        if r.priority:
            doc.field("Priority", r.priority)
        if r.detail:
            doc.field("Detail", _redact_detail(r, view_pii_codes))

    if footer := format_page_footer(total, page, limit):
        doc.text(footer)

    return doc.render()


@with_database_session
@mcp_permission("disposition")
def update_hygiene_issue(*, issue_id: str, disposition: str) -> str:
    """Update the disposition of a hygiene issue (confirm, dismiss, or mute).

    Args:
        issue_id: UUID of the hygiene issue.
        disposition: New disposition. Valid values: 'Confirmed', 'Dismissed', 'Muted'.
    """
    issue_uuid = parse_uuid(issue_id, "issue_id")
    db_disposition = parse_disposition(disposition)
    perms = get_project_permissions()

    updated = HygieneIssue.update_disposition(
        issue_uuid,
        db_disposition,
        HygieneIssue.project_code.in_(perms.allowed_codes),
    )
    if not updated:
        raise MCPResourceNotAccessible("Hygiene issue", issue_id)

    doc = MdDoc()
    doc.text(f"Updated hygiene issue {MdDoc.code(issue_id)} disposition to **{disposition}**.")
    return doc.render()


@with_database_session
@mcp_permission("view")
def get_hygiene_issue(*, issue_id: str) -> str:
    """Get full details of a specific hygiene issue.

    Includes the issue type definition (description, suggested action), profiling run
    metadata, and column-profile context (general type, null rate, distinct count).

    Args:
        issue_id: UUID of the hygiene issue, e.g. from ``list_hygiene_issues`` or
            ``search_hygiene_issues``.
    """
    issue_uuid = parse_uuid(issue_id, "issue_id")
    perms = get_project_permissions()

    detail = HygieneIssue.get_with_context(
        issue_uuid,
        HygieneIssue.project_code.in_(perms.allowed_codes),
    )
    if detail is None:
        raise MCPResourceNotAccessible("Hygiene issue", issue_id)

    location = (
        f"`{detail.column_name}` in `{detail.table_name}`" if detail.column_name else f"`{detail.table_name}`"
    )

    doc = MdDoc()
    doc.heading(1, f"[{detail.priority or 'Unknown'}] {detail.issue_type_name} on {location}")
    doc.field("Issue ID", detail.id, code=True)
    doc.field("Issue Type", detail.issue_type_name)
    doc.field("Schema", detail.schema_name)
    doc.field("Table", detail.table_name)
    if detail.column_name:
        doc.field("Column", detail.column_name)
    if detail.impact_dimension:
        doc.field("Impact Dimension", detail.impact_dimension)
    if detail.dq_dimension:
        doc.field("Quality Dimension", detail.dq_dimension)
    doc.field("Disposition", format_disposition(detail.disposition))
    if detail.priority:
        doc.field("Priority", detail.priority)
    if detail.detail:
        view_pii_codes = set(perms.codes_allowed_to("view_pii"))
        doc.field("Detail", _redact_detail(detail, view_pii_codes))

    if detail.suggested_action:
        doc.heading(2, "Suggested Action")
        doc.text(detail.suggested_action)

    if detail.type_description:
        doc.heading(2, "Issue Type Description")
        doc.text(detail.type_description)

    has_column_profile = detail.column_general_type is not None or detail.column_record_ct is not None
    if has_column_profile:
        doc.heading(2, "Column Profile")
        if detail.column_general_type:
            doc.field("General Type", detail.column_general_type)
        if detail.column_db_data_type:
            doc.field("DB Data Type", detail.column_db_data_type)
        if detail.column_record_ct is not None:
            doc.field("Records", detail.column_record_ct)
        if detail.column_null_value_ct is not None:
            doc.field("Nulls", detail.column_null_value_ct)
            if detail.column_record_ct:
                doc.field("Null Rate", f"{detail.column_null_value_ct / detail.column_record_ct:.2%}")
        if detail.column_distinct_value_ct is not None:
            doc.field("Distinct values", detail.column_distinct_value_ct)

    doc.heading(2, "Profiling Run")
    doc.field("ID", detail.job_execution_id, code=True)
    doc.field("Date", detail.started_at)

    return doc.render()


@with_database_session
@mcp_permission("view")
def search_hygiene_issues(
    *,
    project_code: str | None = None,
    table_group_id: str | None = None,
    issue_type: str | None = None,
    impact_dimension: str | None = None,
    quality_dimension: str | None = None,
    disposition: str | None = "Confirmed",
    issue_likelihood: list[str] | None = None,
    pii_risk: list[str] | None = None,
    since: str | None = None,
    table_name: str | None = None,
    column_name: str | None = None,
    limit: int = 50,
    page: int = 1,
) -> str:
    """Search hygiene issues across profiling runs and table groups.

    To drill into a single run, use ``list_hygiene_issues``.

    Args:
        project_code: Scope to a specific project.
        table_group_id: UUID of a table group to scope to.
        issue_type: Filter by hygiene issue type (e.g. 'Similar Values Match When Standardized').
            See ``testgen://hygiene-issue-types`` for the full list.
        impact_dimension: Filter by impact dimension ('Reliability', 'Conformance',
            'Regularity', 'Usability').
        quality_dimension: Filter by data quality dimension ('Accuracy', 'Completeness',
            'Consistency', 'Recency', 'Timeliness', 'Uniqueness', 'Validity').
        disposition: Filter by disposition. Defaults to 'Confirmed'.
            Valid values: 'Confirmed', 'Dismissed', 'Muted'.
        issue_likelihood: Filter by issue likelihood. Values: 'Definite', 'Likely', 'Possible'.
            Providing this filter auto-excludes PII issues; combine with ``pii_risk`` to include both.
        pii_risk: Filter by PII risk level. Values: 'High', 'Moderate'.
            Providing this filter auto-excludes regular issues.
        since: Include issues from runs that started since this point — e.g. '7 days',
            '2 weeks', '2026-04-01'.
        table_name: Filter by table name (exact match).
        column_name: Filter by column name (exact match).
        limit: Maximum number of issues per page (default 50, max 200).
        page: Page number, starting from 1 (default 1).
    """
    validate_page(page)
    validate_limit(limit, 200)

    perms = get_project_permissions()
    if project_code:
        perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))
        project_codes = [project_code]
    else:
        project_codes = perms.allowed_codes

    table_group_uuid = parse_uuid(table_group_id, "table_group_id") if table_group_id else None
    since_date = parse_since_arg(since) if since else None
    type_id = resolve_issue_type(issue_type) if issue_type else None
    issue_likelihood = parse_issue_likelihood_list(issue_likelihood) if issue_likelihood else None
    pii_risk = parse_pii_risk_list(pii_risk) if pii_risk else None

    clauses = [
        HygieneIssue.project_code.in_(project_codes),
        func.coalesce(HygieneIssue.disposition, Disposition.CONFIRMED) == parse_disposition(disposition or "Confirmed"),
    ]
    if table_group_uuid is not None:
        clauses.append(HygieneIssue.table_groups_id == table_group_uuid)
    if impact_dimension:
        clauses.append(HygieneIssue.impact_dimension == parse_impact_dimension(impact_dimension))
    if quality_dimension:
        clauses.append(HygieneIssueType.dq_dimension == parse_quality_dimension(quality_dimension))
    if type_id:
        clauses.append(HygieneIssue.type_id == type_id)
    if table_name:
        clauses.append(HygieneIssue.table_name == table_name)
    if column_name:
        clauses.append(HygieneIssue.column_name == column_name)
    if since_date is not None:
        clauses.append(JobExecution.started_at >= since_date)
    likelihood_clause = _build_likelihood_clause(issue_likelihood, pii_risk)
    if likelihood_clause is not None:
        clauses.append(likelihood_clause)

    rows, total = HygieneIssue.search(*clauses, page=page, limit=limit)

    doc = MdDoc()
    doc.heading(1, "Hygiene Issue Search")
    if not rows:
        doc.text("_No hygiene issues match the supplied filters._")
        return doc.render()
    if info := format_page_info(total, page, limit):
        doc.text(info)

    view_pii_codes = set(perms.codes_allowed_to("view_pii"))
    for r in rows:
        location = f"`{r.column_name}` in `{r.table_name}`" if r.column_name else f"`{r.table_name}`"
        doc.heading(2, f"[{r.priority or 'Unknown'}] {r.issue_type_name} on {location}")
        doc.field("Issue ID", r.id, code=True)
        doc.field("Issue Type", r.issue_type_name)
        doc.field("Table Group", r.table_groups_name)
        doc.field("Profiling Run", r.job_execution_id, code=True)
        doc.field("Run Date", r.started_at)
        if r.impact_dimension:
            doc.field("Impact Dimension", r.impact_dimension)
        if r.dq_dimension:
            doc.field("Quality Dimension", r.dq_dimension)
        if r.priority:
            doc.field("Priority", r.priority)
        doc.field("Disposition", format_disposition(r.disposition))
        if r.detail:
            doc.field("Detail", _redact_detail(r, view_pii_codes))

    if footer := format_page_footer(total, page, limit):
        doc.text(footer)

    return doc.render()
