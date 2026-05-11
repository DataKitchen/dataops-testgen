from uuid import UUID

from testgen.common.models import with_database_session
from testgen.common.models.data_column import ColumnProfileSummary, DataColumnChars
from testgen.common.models.data_table import DataTable
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profiling_run import ProfilingRun, ProfilingRunSummary
from testgen.common.models.scheduler import RUN_PROFILE_JOB_KEY
from testgen.common.models.table_group import TableGroup, TableGroupSummary
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    format_page_footer,
    format_page_info,
    format_run_duration,
    next_scheduled_run,
    parse_run_status_filter,
    parse_uuid,
    resolve_table_group,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc
from testgen.utils import friendly_score

_DOC_GROUP = DocGroup.BROWSE_PROFILING


@with_database_session
@mcp_permission("catalog")
def get_table(table_group_id: str, table_name: str) -> str:
    """Get an overview of a table with profiling highlights: structural metadata, column list, quality scores, and hygiene issue count from the latest profiling run.

    Args:
        table_group_id: UUID of the table group, e.g. from `get_data_inventory`.
        table_name: Table name exactly as stored in TestGen (case-sensitive).
    """
    tg = resolve_table_group(table_group_id)

    overview = DataTable.get_profiling_overview(tg.id, table_name)
    if overview is None:
        raise MCPUserError(f"Table `{table_name}` not found in this table group.")

    fq_name = f"{overview.schema_name}.{overview.table_name}" if overview.schema_name else overview.table_name

    doc = MdDoc()
    doc.heading(1, f"Table: {fq_name}")
    doc.field("Record count", overview.record_ct)
    doc.field("Column count", overview.column_ct)
    doc.field("Critical data elements", overview.cde_count)
    doc.field("Profiling Score", friendly_score(overview.dq_score_profiling))
    doc.field("Testing Score", friendly_score(overview.dq_score_testing))
    doc.field("Hygiene issues (confirmed)", overview.hygiene_issue_count)
    doc.field("Last profiled", overview.latest_profile_started_at)
    doc.field("Profiling Run", overview.latest_profile_job_execution_id, code=True)

    if overview.columns:
        doc.heading(2, "Columns")
        doc.table(
            ["Column", "Type", "Functional type", "DB type", "Has nulls"],
            [
                [c.column_name, c.general_type, c.functional_data_type, c.db_data_type, c.has_nulls]
                for c in overview.columns
            ],
            code=[0],
        )
    else:
        doc.text("_No columns recorded for this table._")

    return doc.render()


@with_database_session
@mcp_permission("catalog")
def list_column_profiles(
    table_group_id: str,
    table_name: str | None = None,
    columns: list[str] | None = None,
    job_execution_id: str | None = None,
    limit: int = 100,
    page: int = 1,
) -> str:
    """List per-column profile headers (~14 fields each) — the Layer 1 scan of profiling results across columns in a table group.

    Args:
        table_group_id: UUID of the table group, e.g. from `get_data_inventory`.
        table_name: Optional — scope to one table (case-sensitive).
        columns: Optional — specific column names to include (case-sensitive).
        job_execution_id: UUID of a profiling run, e.g. from `get_table` or
            `list_profiling_summaries`. When omitted, each column uses its own
            latest run.
        limit: Page size (default 100).
        page: Page number starting at 1 (default 1).
    """
    tg = resolve_table_group(table_group_id)

    profiling_run_id: UUID | None = None
    if job_execution_id:
        run_uuid = parse_uuid(job_execution_id, "job_execution_id")
        profiling_run = ProfilingRun.get_by_id_or_job(run_uuid)
        if profiling_run is None or profiling_run.table_groups_id != tg.id:
            raise MCPResourceNotAccessible("Profiling run", job_execution_id)
        profiling_run_id = profiling_run.id

    clauses = []
    if table_name:
        clauses.append(DataColumnChars.table_name == table_name)
    if columns:
        clauses.append(DataColumnChars.column_name.in_(columns))

    data, total = DataColumnChars.list_for_table_group(
        *clauses,
        table_groups_id=tg.id,
        profiling_run_id=profiling_run_id,
        page=page,
        limit=limit,
    )

    if not data:
        if page > 1:
            return f"No column profiles on page {page} (total: {total})."
        return f"No column profiles found for table group `{table_group_id}`."

    doc = MdDoc()
    scope_descriptor = f"table group `{table_group_id}`"
    if table_name:
        scope_descriptor = f"table `{table_name}` in {scope_descriptor}"
    doc.heading(1, f"Column profiles for {scope_descriptor}")

    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    headers = [
        "Column", "Table", "Type", "Functional type", "Suggestion",
        "PII", "CDE",
        "Records", "Nulls", "Distinct", "Filled",
        "Profiling Score", "Testing Score", "Hygiene issues",
    ]
    rows = [_render_column_profile_row(c) for c in data]
    doc.table(headers, rows, code=[0, 1])

    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)

    return doc.render()


@with_database_session
@mcp_permission("catalog")
def list_profiling_summaries(
    table_group_id: str | None = None,
    project_code: str | None = None,
    limit: int = 20,
    page: int = 1,
) -> str:
    """List aggregated profiling health summaries for a table group or across a project — quality scores, hygiene issue counts, record counts, last profiled date.

    Args:
        table_group_id: UUID of a specific table group, e.g. from
            `get_data_inventory`. Returns just that group's summary. Mutually
            exclusive with `project_code`.
        project_code: Project code to summarize all table groups within, e.g.
            from `list_projects`. Returns all groups, paginated. Mutually
            exclusive with `table_group_id`.
        limit: Page size when iterating table groups in a project (default 20).
        page: Page number starting at 1 (default 1).
    """
    if table_group_id and project_code:
        raise MCPUserError("Pass either `table_group_id` or `project_code`, not both.")
    if not table_group_id and not project_code:
        raise MCPUserError("Provide either `table_group_id` or `project_code`.")

    if table_group_id:
        tg = resolve_table_group(table_group_id)
        summaries, _ = TableGroup.select_summary(tg.project_code, table_group_id=tg.id)
        if not summaries:
            return f"No table group found for `{table_group_id}`."

        doc = MdDoc()
        doc.heading(1, f"Profiling summary for table group `{table_group_id}`")
        for s in summaries:
            _render_table_group_summary(doc, s)
        return doc.render()

    perms = get_project_permissions()
    perms.verify_access(
        project_code,
        not_found=MCPResourceNotAccessible("Project", project_code),
    )
    summaries, total = TableGroup.select_summary(project_code, page=page, page_size=limit)
    if not summaries:
        if page > 1:
            return f"No table groups on page {page} (total: {total})."
        return f"No table groups in project `{project_code}`."

    doc = MdDoc()
    doc.heading(1, f"Profiling summary for project `{project_code}`")
    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)
    for s in summaries:
        _render_table_group_summary(doc, s)
    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)
    return doc.render()


_PII_RISK_MAP = {"A": "High", "B": "Moderate", "C": "Low"}
_PII_TYPE_MAP = {"ID": "ID", "NAME": "Name", "DEMO": "Demographic", "CONTACT": "Contact"}


def _format_pii(value: str | None) -> str | None:
    """Render a `pii_flag` value as a human label. Mirrors `PiiDisplay` in metadata_tags.js."""
    if not value:
        return None
    if value == "MANUAL":
        return "PII"
    risk, _, rest = value.partition("/")
    type_code, _, detail = rest.partition("/")
    risk_label = _PII_RISK_MAP.get(risk, "Moderate")
    type_label = _PII_TYPE_MAP.get(type_code)
    caption = f"{risk_label} Risk"
    if type_label:
        caption += f" - {type_label}"
    if detail and detail != type_label:
        caption += f" / {detail}"
    return f"PII ({caption})"


def _render_column_profile_row(c: ColumnProfileSummary) -> list:
    return [
        c.column_name,
        c.table_name,
        c.general_type,
        c.functional_data_type,
        c.datatype_suggestion,
        _format_pii(c.pii_flag),
        "Y" if c.critical_data_element else None,
        c.record_ct,
        c.null_value_ct,
        c.distinct_value_ct,
        c.filled_value_ct,
        friendly_score(c.dq_score_profiling),
        friendly_score(c.dq_score_testing),
        c.hygiene_issue_count,
    ]


@with_database_session
@mcp_permission("catalog")
def list_profiling_runs(
    table_group_id: str,
    status: str | None = None,
    limit: int = 10,
    page: int = 1,
) -> str:
    """List profiling run history for a table group, including queued, in-progress, and failed runs.
    Ordered by submission time descending.

    Args:
        table_group_id: UUID of the table group, e.g. from `get_data_inventory`.
        status: Optional run status filter. One of: Pending, Running, Completed, Canceled, Error.
        limit: Page size (default 10, max 100).
        page: Page number starting at 1 (default 1).
    """
    validate_limit(limit, 100)
    validate_page(page)

    statuses = parse_run_status_filter(status) if status else None
    tg = resolve_table_group(table_group_id)

    summaries, total = ProfilingRun.select_summary(
        project_code=tg.project_code,
        table_group_id=tg.id,
        statuses=statuses,
        page=page,
        page_size=limit,
    )

    # Queued/claimed JEs that don't yet have a profiling_runs row are invisible to TG-scoped
    # joined-run queries. Surface them as a separate "Pending" section on page 1.
    pending_jes: list[JobExecution] = []
    if page == 1:
        pending_jes = JobExecution.select_active_by_kwargs(
            project_code=tg.project_code,
            job_key=RUN_PROFILE_JOB_KEY,
            kwargs_match={"table_group_id": str(tg.id)},
            statuses=statuses,
        )

    doc = MdDoc()
    scope = f" — status `{status}`" if status else ""
    doc.heading(1, f"Profiling runs for `{tg.table_groups_name}`{scope}")

    next_run = next_scheduled_run(
        RUN_PROFILE_JOB_KEY, {"table_group_id": str(tg.id)}, tg.project_code
    )
    if next_run:
        doc.field("Next scheduled run", next_run)

    if pending_jes:
        doc.heading(2, f"Pending ({len(pending_jes)})")
        for je in pending_jes:
            _render_pending_profiling_je(doc, je, label=tg.table_groups_name)

    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    if not summaries:
        if page > 1:
            doc.text(f"_No profiling runs on page {page} (total: {total})._")
        elif not pending_jes:
            doc.text("_No profiling runs found._")
        return doc.render()

    for run in summaries:
        _render_profiling_run_section(doc, run)

    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)

    return doc.render()


@with_database_session
@mcp_permission("catalog")
def get_profiling_run(job_execution_id: str) -> str:
    """Get a single profiling run with status, timing, totals, and per-table breakdown. Returns the
    run regardless of state — including queued and in-progress runs without complete results yet.
    The per-table breakdown is only available after the run completes.

    Args:
        job_execution_id: UUID of a profiling run, e.g. from `list_profiling_runs` or
            `list_profiling_summaries`.
    """
    parse_uuid(job_execution_id, "job_execution_id")
    perms = get_project_permissions()

    summaries, _ = ProfilingRun.select_summary(job_execution_id=job_execution_id, page_size=1)
    summary = summaries[0] if summaries else None
    if summary is None or summary.project_code not in perms.allowed_codes:
        raise MCPResourceNotAccessible("Profiling run", job_execution_id)

    doc = MdDoc()
    tg_label = summary.table_groups_name or "—"
    doc.heading(1, f"Profiling run: {tg_label}")
    doc.field("Job ID", summary.job_execution_id, code=True)
    if summary.table_groups_name:
        doc.field("Table group", summary.table_groups_name)
    if summary.table_group_schema:
        doc.field("Schema", summary.table_group_schema)
    doc.field("Status", summary.status_label)
    doc.field("Submitted", summary.created_at)
    doc.field("Started", summary.started_at or "—")
    doc.field("Ended", summary.completed_at or "In progress")
    duration = format_run_duration(summary.started_at, summary.completed_at)
    if duration:
        doc.field("Duration", duration)

    has_totals = summary.table_ct or summary.column_ct or summary.record_ct or summary.anomaly_ct
    if has_totals:
        doc.field("Tables profiled", summary.table_ct or 0)
        doc.field("Columns profiled", summary.column_ct or 0)
        if summary.record_ct is not None:
            doc.field("Records", summary.record_ct)
        doc.field(
            "Hygiene issues (confirmed)",
            f"{(summary.anomalies_definite_ct or 0) + (summary.anomalies_likely_ct or 0) + (summary.anomalies_possible_ct or 0)} total "
            f"— {summary.anomalies_definite_ct or 0} definite, "
            f"{summary.anomalies_likely_ct or 0} likely, "
            f"{summary.anomalies_possible_ct or 0} possible",
        )
        if summary.dq_score_profiling is not None:
            doc.field("Profiling Score", friendly_score(summary.dq_score_profiling))

    if summary.profiling_run_id:
        breakdown = ProfilingRun.select_table_breakdown(summary.profiling_run_id)
        if breakdown:
            doc.heading(2, "Per-table breakdown")
            doc.table(
                ["Schema", "Table", "Records", "Columns", "Hygiene issues"],
                [
                    [r.schema_name, r.table_name, r.record_ct, r.column_ct, r.anomaly_ct]
                    for r in breakdown
                ],
                code=[0, 1],
            )

    if summary.error_message:
        doc.heading(2, "Error")
        doc.text(summary.error_message)

    return doc.render()


def _render_pending_profiling_je(doc: MdDoc, je: JobExecution, label: str) -> None:
    status_label = ProfilingRunSummary.STATUS_LABEL.get(je.status, je.status)
    doc.heading(3, f"{label} — {status_label}")
    doc.field("Job ID", je.id, code=True)
    doc.field("Submitted", je.created_at)
    doc.field("Started", je.started_at or "—")
    doc.field("Ended", je.completed_at or "In progress")


def _render_profiling_run_section(doc: MdDoc, run: ProfilingRunSummary) -> None:
    title = run.table_groups_name or run.profiling_run_id or run.job_execution_id
    doc.heading(2, f"{title} — {run.status_label}")
    doc.field("Job ID", run.job_execution_id, code=True)
    doc.field("Submitted", run.created_at)
    doc.field("Started", run.started_at or "—")
    doc.field("Ended", run.completed_at or "In progress")
    duration = format_run_duration(run.started_at, run.completed_at)
    if duration:
        doc.field("Duration", duration)

    if run.table_ct or run.column_ct:
        doc.field("Tables profiled", run.table_ct or 0)
        doc.field("Columns profiled", run.column_ct or 0)
    if run.anomaly_ct is not None and (
        run.anomalies_definite_ct or run.anomalies_likely_ct or run.anomalies_possible_ct
    ):
        doc.field(
            "Hygiene issues (confirmed)",
            f"{(run.anomalies_definite_ct or 0) + (run.anomalies_likely_ct or 0) + (run.anomalies_possible_ct or 0)} total",
        )
    if run.dq_score_profiling is not None:
        doc.field("Profiling Score", friendly_score(run.dq_score_profiling))


def _render_table_group_summary(doc: MdDoc, s: TableGroupSummary) -> None:
    doc.heading(2, s.table_groups_name)
    if s.connection_name:
        doc.field("Connection", s.connection_name)
    doc.field("Table group", s.id, code=True)

    if not s.latest_profile_id:
        doc.text("_Not profiled yet._")
        return

    doc.field("Tables", s.table_ct or 0)
    doc.field("Columns", s.column_ct or 0)
    doc.field("Records", s.record_ct or 0)
    doc.field("Profiling Score", friendly_score(s.dq_score_profiling))
    doc.field("Testing Score", friendly_score(s.dq_score_testing))
    doc.field(
        "Hygiene issues (confirmed)",
        f"{(s.latest_hygiene_issues_definite_ct or 0) + (s.latest_hygiene_issues_likely_ct or 0) + (s.latest_hygiene_issues_possible_ct or 0)} total "
        f"— {s.latest_hygiene_issues_definite_ct or 0} definite, "
        f"{s.latest_hygiene_issues_likely_ct or 0} likely, "
        f"{s.latest_hygiene_issues_possible_ct or 0} possible",
    )
    doc.field("Last profiled", s.latest_profile_start)
    doc.field("Profiling Run", s.latest_profile_job_execution_id, code=True)
    if s.monitor_lookback_end:
        doc.field("Last monitored", s.monitor_lookback_end)
