import dataclasses
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field
from sqlalchemy import func, or_

from testgen.common.data_catalog_service import build_create_table_script
from testgen.common.database.column_chars import ObjectType
from testgen.common.database.table_group_service import (
    schema_label_for_table_group,
    table_group_qualifies_table_refs,
)
from testgen.common.enums import JOB_STATUS_LABEL, PII_FLAG_PREFIX_TO_LABEL, JobKey, JobStatus
from testgen.common.flavors import table_group_schema_label
from testgen.common.models import with_database_session
from testgen.common.models.data_column import (
    GENERAL_TYPE_CODE_TO_LABEL,
    SUGGESTED_DATA_TYPE_TO_PREFIX,
    ColumnOrderBy,
    ColumnProfileDetail,
    ColumnProfileSummary,
    DataColumnChars,
)
from testgen.common.models.data_table import CatalogLevel, CatalogTag, DataTable, column_cde, parse_catalog_tags
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.job_execution import QUEUED_MESSAGE, JobExecution
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import ProfilingRun, ProfilingRunSummary
from testgen.common.models.scheduler import RUN_PROFILE_JOB_KEY
from testgen.common.models.table_group import TableGroup, TableGroupSummary
from testgen.common.pii_masking import PII_REDACTED, mask_profiling_pii
from testgen.common.profile_frequency import format_frequent, frequent_entries
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.services.source_data_protection import mcp_source_data_only, mcp_source_data_protected
from testgen.mcp.tools.common import (
    DocGroup,
    build_contains_pattern,
    build_ilike_pattern,
    format_catalog_tags_cell,
    format_page_footer,
    format_page_info,
    format_run_duration,
    format_semantic_table_type,
    next_scheduled_run,
    parse_column_order_by,
    parse_general_type,
    parse_pii_category,
    parse_pii_risk_level,
    parse_run_status_filter,
    parse_suggested_data_type,
    parse_uuid,
    render_catalog_tags,
    require_filter_text,
    resolve_profiling_run,
    resolve_table_group,
    run_status_filter_options,
    tag_filter_clauses,
    tag_filter_description,
    target_db_error_text,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc
from testgen.utils import friendly_score

_DOC_GROUP = DocGroup.BROWSE_PROFILING
_COLUMN_ERRORS_LIMIT = 20


def _qualified_table_name(schema_name: str | None, table_name: str, qualifies: bool) -> str:
    return f"{schema_name}.{table_name}" if qualifies and schema_name else table_name


@with_database_session
@mcp_permission("catalog")
def get_table(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    table_name: Annotated[str, Field(description="Table name exactly as stored in TestGen (case-sensitive).")],
) -> str:
    """Get a table's catalog metadata, latest profile, and column list.

    Returns structural metadata, the semantic table type, quality scores, the description, critical data element
    flag, and catalog tags, then the latest completed profiling run and the column list. When the table has no value
    of its own for a tag, the table group's value is shown, marked as inherited. Tags with no value are omitted. A
    table that has not been profiled returns its catalog metadata only.
    """
    tg = resolve_table_group(table_group_id)

    overview = DataTable.get_profiling_overview(tg.id, table_name)
    if overview is None:
        raise MCPUserError(f"Table `{table_name}` not found in this table group.")

    fq_name = _qualified_table_name(
        overview.schema_name, overview.table_name, table_group_qualifies_table_refs(tg.id)
    )

    doc = MdDoc()
    doc.heading(1, f"Table: {fq_name}")
    if overview.object_type == ObjectType.FILES:
        doc.field("Object type", overview.object_type.title())
        doc.field("File count", overview.file_ct)
    doc.field("Semantic table type", format_semantic_table_type(overview.functional_table_type))
    doc.field("Record count", overview.record_ct)
    doc.field("Column count", overview.column_ct)
    doc.field("Critical data element columns", overview.cde_count)
    doc.field("Profiling Score", friendly_score(overview.dq_score_profiling))
    doc.field("Testing Score", friendly_score(overview.dq_score_testing))

    doc.heading(2, "Catalog metadata")
    if overview.description:
        doc.field("Description", _inline_text(overview.description))
    doc.field("Critical data element", overview.critical_data_element)
    render_catalog_tags(doc, parse_catalog_tags(overview.catalog_tags))

    doc.heading(2, "Profile")
    if overview.latest_profile_job_execution_id:
        doc.field("Profiling Run", overview.latest_profile_job_execution_id, code=True)
        doc.field("Profiled at", overview.latest_profile_started_at)
        doc.field("Hygiene issues (confirmed)", overview.hygiene_issue_count)
    else:
        doc.text("_This table has not been profiled yet. Run profiling for the table group with `run_profiling`._")

    if overview.columns:
        doc.heading(2, "Columns")
        doc.table(
            ["Column", "General Type", "Semantic Data Type", "DB Type", "Has Nulls"],
            [
                [
                    c.column_name,
                    _format_general_type(c.general_type),
                    c.functional_data_type,
                    c.db_data_type,
                    c.has_nulls,
                ]
                for c in overview.columns
            ],
            code=[0],
        )
    else:
        doc.text("_No columns recorded for this table._")

    return doc.render()


def _inline_text(value: str) -> str:
    """User-entered free text for a single field line: markdown escaped, line breaks folded."""
    return MdDoc.escape(" ".join(value.splitlines()))


@with_database_session
@mcp_permission("catalog")
def list_columns(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    table_name: Annotated[str | None, Field(description="Optional — scope to one table (case-sensitive).")] = None,
    columns: Annotated[
        list[str] | None,
        Field(description="Optional — specific column names to include (case-sensitive)."),
    ] = None,
    job_execution_id: Annotated[
        str | None,
        Field(
            description="UUID of a profiling run, e.g. from `get_table` or `list_profiling_summaries`. When omitted, "
            "each column uses its own latest run.",
        ),
    ] = None,
    null_ratio_above: Annotated[
        float | None,
        Field(description="Match columns whose null fraction exceeds this value (e.g. `0.2` for above 20% null)."),
    ] = None,
    null_ratio_below: Annotated[
        float | None,
        Field(description="Match columns whose null fraction is below this value."),
    ] = None,
    distinct_ratio_above: Annotated[
        float | None,
        Field(
            description="Match columns whose distinct-value fraction exceeds this value (e.g. `0.95` for near-unique "
            "columns).",
        ),
    ] = None,
    distinct_ratio_below: Annotated[
        float | None,
        Field(
            description="Match columns whose distinct-value fraction is below this value (e.g. `0.001` for low "
            "cardinality).",
        ),
    ] = None,
    filled_ratio_above: Annotated[
        float | None,
        Field(description="Match columns whose dummy/placeholder-value fraction exceeds this value."),
    ] = None,
    filled_ratio_below: Annotated[
        float | None,
        Field(description="Match columns whose dummy/placeholder-value fraction is below this value."),
    ] = None,
    score_profiling_above: Annotated[
        float | None,
        Field(description="Match columns whose Profiling Score is above this value (0-100 scale)."),
    ] = None,
    score_profiling_below: Annotated[
        float | None,
        Field(description="Match columns whose Profiling Score is below this value (0-100 scale)."),
    ] = None,
    score_testing_above: Annotated[
        float | None,
        Field(description="Match columns whose Testing Score is above this value (0-100 scale)."),
    ] = None,
    score_testing_below: Annotated[
        float | None,
        Field(description="Match columns whose Testing Score is below this value (0-100 scale)."),
    ] = None,
    pii: Annotated[
        bool | None,
        Field(description="When `true`, match columns flagged as PII; when `false`, exclude PII columns."),
    ] = None,
    cde: Annotated[
        bool | None,
        Field(
            description="When `true`, match columns that are a critical data element by their own flag or, when they "
            "have none, the table's; when `false`, match the rest.",
        ),
    ] = None,
    xde: Annotated[
        bool | None,
        Field(
            description="When `true`, match only columns marked as an excluded data element; when `false`, omit them.",
        ),
    ] = None,
    suggested_data_type: Annotated[
        str | None,
        Field(
            description="Match columns where profiling suggests a more suitable data type. Pass `Any` for any "
            "mismatch, or a concrete type (`Smallint`, `Integer`, `Bigint`, `Decimal`, `Numeric`, `Varchar`, `Date`, "
            "`Timestamp`, `Boolean`) to filter mismatches whose suggestion starts with that type. Columns where the "
            "suggestion matches the column's stored type are always excluded.",
        ),
    ] = None,
    general_type: Annotated[
        str | None,
        Field(description="Broad type classification — `Alpha`, `Numeric`, `Datetime`, `Boolean`, `Time`, or `Other`."),
    ] = None,
    semantic_data_type: Annotated[
        str | None,
        Field(
            description="Matches columns whose semantic data type contains this text, ignoring case. Use `%` as a "
            "wildcard within the text. See `testgen://column-profile-fields` for the values profiling assigns.",
        ),
    ] = None,
    pii_category: Annotated[
        str | None,
        Field(description="PII category — `ID`, `Name`, `Demographic`, or `Contact`."),
    ] = None,
    pii_risk_level: Annotated[str | None, Field(description="PII risk level — `High`, `Moderate`, or `Low`.")] = None,
    data_source: Annotated[str | None, Field(description=tag_filter_description("data_source", CatalogLevel.COLUMN))] = None,
    source_system: Annotated[
        str | None, Field(description=tag_filter_description("source_system", CatalogLevel.COLUMN))
    ] = None,
    source_process: Annotated[
        str | None, Field(description=tag_filter_description("source_process", CatalogLevel.COLUMN))
    ] = None,
    business_domain: Annotated[
        str | None, Field(description=tag_filter_description("business_domain", CatalogLevel.COLUMN))
    ] = None,
    stakeholder_group: Annotated[
        str | None, Field(description=tag_filter_description("stakeholder_group", CatalogLevel.COLUMN))
    ] = None,
    transform_level: Annotated[
        str | None, Field(description=tag_filter_description("transform_level", CatalogLevel.COLUMN))
    ] = None,
    aggregation_level: Annotated[
        str | None, Field(description=tag_filter_description("aggregation_level", CatalogLevel.COLUMN))
    ] = None,
    data_product: Annotated[str | None, Field(description=tag_filter_description("data_product", CatalogLevel.COLUMN))] = None,
    data_classification: Annotated[
        str | None, Field(description=tag_filter_description("data_classification", CatalogLevel.COLUMN))
    ] = None,
    order_by: Annotated[
        str | None,
        Field(
            description="Sort key — `Null Ratio`, `Distinct Ratio`, `Filled Ratio`, `Profiling Score`, `Testing "
            "Score`, or `Hygiene Count`. Defaults to table/column position.",
        ),
    ] = None,
    limit: Annotated[int, Field(description="Page size (default 100, max 500).")] = 100,
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
) -> str:
    """List the columns of a table group with catalog flags, tags, and profile headers.

    Lists profiled and unprofiled columns, or, with `job_execution_id`, the columns that run profiled. Filters combine
    with AND. Filters on profile values match only profiled columns. Tag filters match the column's own value or, when
    it has none, the table's or table group's.
    """
    validate_page(page)
    validate_limit(limit, 500)

    tg = resolve_table_group(table_group_id)

    profiling_run_id: UUID | None = None
    if job_execution_id:
        profiling_run = resolve_profiling_run(job_execution_id)
        if profiling_run.table_groups_id != tg.id:
            raise MCPResourceNotAccessible("Profiling run", job_execution_id)
        profiling_run_id = profiling_run.id

    clauses = []
    if table_name:
        clauses.append(DataColumnChars.table_name == table_name)
    if columns:
        clauses.append(DataColumnChars.column_name.in_(columns))

    profile_clauses = []
    if null_ratio_above is not None:
        profile_clauses.append(ProfileResult.null_value_ct * 1.0 / func.nullif(ProfileResult.record_ct, 0) > null_ratio_above)
    if null_ratio_below is not None:
        profile_clauses.append(ProfileResult.null_value_ct * 1.0 / func.nullif(ProfileResult.record_ct, 0) < null_ratio_below)
    if distinct_ratio_above is not None:
        profile_clauses.append(
            ProfileResult.distinct_value_ct * 1.0 / func.nullif(ProfileResult.record_ct, 0) > distinct_ratio_above
        )
    if distinct_ratio_below is not None:
        profile_clauses.append(
            ProfileResult.distinct_value_ct * 1.0 / func.nullif(ProfileResult.record_ct, 0) < distinct_ratio_below
        )
    if filled_ratio_above is not None:
        profile_clauses.append(
            ProfileResult.filled_value_ct * 1.0 / func.nullif(ProfileResult.record_ct, 0) > filled_ratio_above
        )
    if filled_ratio_below is not None:
        profile_clauses.append(
            ProfileResult.filled_value_ct * 1.0 / func.nullif(ProfileResult.record_ct, 0) < filled_ratio_below
        )

    if score_profiling_above is not None:
        profile_clauses.append(DataColumnChars.dq_score_profiling > score_profiling_above / 100)
    if score_profiling_below is not None:
        profile_clauses.append(DataColumnChars.dq_score_profiling < score_profiling_below / 100)
    if score_testing_above is not None:
        clauses.append(DataColumnChars.dq_score_testing > score_testing_above / 100)
    if score_testing_below is not None:
        clauses.append(DataColumnChars.dq_score_testing < score_testing_below / 100)

    if pii is True:
        clauses.append(DataColumnChars.pii_flag.isnot(None))
    elif pii is False:
        clauses.append(DataColumnChars.pii_flag.is_(None))

    if cde is not None:
        clauses.append(column_cde().is_(cde))
    if xde is not None:
        clauses.append(func.coalesce(DataColumnChars.excluded_data_element, False).is_(xde))

    if suggested_data_type is not None:
        prefix = SUGGESTED_DATA_TYPE_TO_PREFIX[parse_suggested_data_type(suggested_data_type)]
        if prefix is None:
            profile_clauses.append(ProfileResult.datatype_suggestion.isnot(None))
        else:
            profile_clauses.append(ProfileResult.datatype_suggestion.ilike(f"{prefix}%"))

    if general_type is not None:
        clauses.append(DataColumnChars.general_type == parse_general_type(general_type))
    if semantic_data_type is not None:
        require_filter_text("semantic_data_type", semantic_data_type)
        profile_clauses.append(
            DataColumnChars.functional_data_type.ilike(
                build_contains_pattern(semantic_data_type), escape="\\"
            )
        )
    if pii_category is not None:
        category = parse_pii_category(pii_category)
        # ``pii_flag`` stores ``<risk>/<category>/<detail>``; match on the middle segment.
        clauses.append(DataColumnChars.pii_flag.like(f"%/{category}/%"))
    if pii_risk_level is not None:
        risk_code = parse_pii_risk_level(pii_risk_level)
        # ``MANUAL`` is user-set PII, weighted equivalent to ``A`` (High) by ``dq_score_weight_defaults``.
        if risk_code == "A":
            clauses.append(
                or_(
                    DataColumnChars.pii_flag.like("A/%"),
                    DataColumnChars.pii_flag == "MANUAL",
                )
            )
        else:
            clauses.append(DataColumnChars.pii_flag.like(f"{risk_code}/%"))

    clauses.extend(tag_filter_clauses(
        {
            "data_source": data_source,
            "source_system": source_system,
            "source_process": source_process,
            "business_domain": business_domain,
            "stakeholder_group": stakeholder_group,
            "transform_level": transform_level,
            "aggregation_level": aggregation_level,
            "data_product": data_product,
            "data_classification": data_classification,
        },
        CatalogLevel.COLUMN,
    ))
    if profile_clauses:
        clauses.extend([ProfileResult.profile_run_id.isnot(None), *profile_clauses])

    order_value: ColumnOrderBy | None = parse_column_order_by(order_by) if order_by else None

    data, total = DataColumnChars.list_for_table_group(
        *clauses,
        table_groups_id=tg.id,
        profiling_run_id=profiling_run_id,
        order_by=order_value,
        page=page,
        limit=limit,
    )

    if not data:
        if page > 1:
            return f"No columns on page {page} (total: {total})."
        if clauses:
            return "No columns match the supplied filters."
        return f"No columns found for table group `{table_group_id}`."

    doc = MdDoc()
    scope_descriptor = f"table group `{table_group_id}`"
    if table_name:
        scope_descriptor = f"table `{table_name}` in {scope_descriptor}"
    doc.heading(1, f"Columns in {scope_descriptor}")

    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    headers = [
        "Column", "Table", "General Type", "Semantic Data Type", "Suggestion",
        "PII", "CDE", "XDE",
        "Records", "Nulls", "Distinct", "Filled",
        "Profiling Score", "Testing Score", "Hygiene Issues", "Catalog Tags",
    ]
    rows = []
    any_inherited = False
    for column in data:
        catalog_tags = parse_catalog_tags(column.catalog_tags)
        any_inherited = any_inherited or any(tag.inherited_from for tag in catalog_tags)
        rows.append(_render_column_row(column, catalog_tags))
    doc.table(headers, rows, code=[0, 1])
    if any_inherited:
        doc.text("_A tag value marked (table) or (table group) is inherited from the column's table or table group._")

    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)

    return doc.render()


@with_database_session
@mcp_permission("catalog")
def list_profiling_summaries(
    table_group_id: Annotated[
        str | None,
        Field(
            description="UUID of a specific table group, e.g. from `get_data_inventory`. Returns just that group's "
            "summary. Mutually exclusive with `project_code`.",
        ),
    ] = None,
    project_code: Annotated[
        str | None,
        Field(
            description="Project code to summarize all table groups within, e.g. from `list_projects`. Returns all "
            "groups, paginated. Mutually exclusive with `table_group_id`.",
        ),
    ] = None,
    limit: Annotated[int, Field(description="Page size when iterating table groups in a project (default 20).")] = 20,
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
) -> str:
    """List aggregated profiling health summaries for a table group or project.
    Covers quality scores, hygiene issue counts, record counts, and last profiled date.
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


_PII_TYPE_MAP = {"ID": "ID", "NAME": "Name", "DEMO": "Demographic", "CONTACT": "Contact"}


def _format_pii(value: str | None) -> str | None:
    """Render a `pii_flag` value as a human label. Mirrors `PiiDisplay` in metadata_tags.js."""
    if not value:
        return "No"
    if value == "MANUAL":
        return "Yes"
    risk, _, rest = value.partition("/")
    type_code, _, detail = rest.partition("/")
    risk_label = PII_FLAG_PREFIX_TO_LABEL.get(risk, "Moderate")
    type_label = _PII_TYPE_MAP.get(type_code)
    caption = f"{risk_label} Risk"
    if type_label:
        caption += f" - {type_label}"
    if detail and detail != type_label:
        caption += f" / {detail}"
    return f"Yes ({caption})"


def _with_provenance_label(value: Any, provenance: str | None) -> Any:
    return f"{value} ({provenance})" if value is not None and provenance else value


def _render_column_row(c: ColumnProfileSummary, catalog_tags: list[CatalogTag]) -> list:
    return [
        c.column_name,
        c.table_name,
        _format_general_type(c.general_type),
        c.functional_data_type,
        c.datatype_suggestion,
        _format_pii(c.pii_flag),
        "Y" if c.critical_data_element else "",
        "Y" if c.excluded_data_element else "",
        c.record_ct,
        c.null_value_ct,
        c.distinct_value_ct,
        _with_provenance_label(c.filled_value_ct, ProfileResult.provenance_label("filled_value_ct", vars(c))),
        friendly_score(c.dq_score_profiling),
        friendly_score(c.dq_score_testing),
        c.hygiene_issue_count,
        format_catalog_tags_cell(catalog_tags),
    ]


@with_database_session
@mcp_permission("catalog")
def list_profiling_runs(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    schedule_id: Annotated[
        str | None,
        Field(
            description="Optional UUID of a schedule, e.g. from `list_schedules`. Returns only runs triggered by that "
            "schedule.",
        ),
    ] = None,
    status: Annotated[
        str | None,
        Field(description=f"Optional run status filter. One of: {run_status_filter_options(JobKey.run_profile)}."),
    ] = None,
    limit: Annotated[int, Field(description="Page size (default 10, max 100).")] = 10,
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
) -> str:
    """List profiling run history for a table group.
    Includes queued, in-progress, and failed runs, ordered by submission time descending.
    """
    validate_limit(limit, 100)
    validate_page(page)

    statuses = parse_run_status_filter(status, JobKey.run_profile) if status else None
    if schedule_id:
        parse_uuid(schedule_id, "schedule_id")
    tg = resolve_table_group(table_group_id)

    summaries, total = ProfilingRun.select_summary(
        project_code=tg.project_code,
        table_group_id=tg.id,
        schedule_id=schedule_id,
        statuses=statuses,
        page=page,
        page_size=limit,
    )

    # Queued/claimed JEs that don't yet have a profiling_runs row are invisible to TG-scoped
    # joined-run queries. Surface them as a separate "Pending" section on page 1.
    pending_jes: list[JobExecution] = []
    if page == 1:
        clauses = [JobExecution.job_schedule_id == schedule_id] if schedule_id else []
        pending_jes = JobExecution.select_active_by_kwargs(
            *clauses,
            project_code=tg.project_code,
            job_key=RUN_PROFILE_JOB_KEY,
            kwargs_match={"table_group_id": str(tg.id)},
            statuses=statuses,
        )

    doc = MdDoc()
    scope_parts = []
    if schedule_id:
        scope_parts.append(f"schedule `{schedule_id}`")
    if status:
        scope_parts.append(f"status `{status}`")
    scope = f" — {', '.join(scope_parts)}" if scope_parts else ""
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
def get_profiling_run(
    job_execution_id: Annotated[
        str,
        Field(description="UUID of a profiling run, e.g. from `list_profiling_runs` or `list_profiling_summaries`."),
    ],
) -> str:
    """Get a single profiling run with status, timing, and totals.
    Returns the run regardless of state — including queued and in-progress runs without
    complete results yet. The per-table breakdown is only available after the run completes.
    """
    parse_uuid(job_execution_id, "job_execution_id")
    perms = get_project_permissions()

    summaries, _ = ProfilingRun.select_summary(job_execution_id=job_execution_id, page_size=1)
    summary = summaries[0] if summaries else None
    if summary is None or summary.project_code not in perms.allowed_codes:
        raise MCPResourceNotAccessible("Profiling run", job_execution_id)

    table_group_name = summary.table_groups_name
    if summary.profiling_run_id is None:
        job = JobExecution.get(summary.job_execution_id)
        table_group = TableGroup.get(job.kwargs.get("table_group_id", "")) if job else None
        table_group_name = table_group.table_groups_name if table_group else None

    doc = MdDoc()
    tg_label = table_group_name or "—"
    schema_label = table_group_schema_label(summary.sql_flavor_code)
    doc.heading(1, f"Profiling run: {tg_label}")
    doc.field("Profiling Run", summary.job_execution_id, code=True)
    if table_group_name:
        doc.field("Table group", table_group_name)
    if schema_label and summary.table_group_schema:
        doc.field(schema_label, summary.table_group_schema)
    doc.field("Status", summary.status_label)
    if summary.status == JobStatus.QUEUED:
        doc.text(QUEUED_MESSAGE)
    doc.field("Submitted", summary.created_at)
    doc.field("Started", summary.started_at or "—")
    doc.field("Ended", summary.completed_at or "In progress")
    duration = format_run_duration(summary.active_seconds, summary.status)
    if duration:
        doc.field("Duration", duration)

    has_totals = summary.table_ct or summary.column_ct or summary.record_ct or summary.anomaly_ct
    if has_totals:
        doc.field("Tables profiled", summary.table_ct or 0)
        doc.field("Columns profiled", summary.column_ct or 0)
        _render_provenance_counts(doc, summary)
        if summary.record_ct is not None:
            doc.field("Records", summary.record_ct)
        if summary.profiling_run_id:
            # Count from the canonical source so likelihood buckets and Potential PII
            # stay separate (matches the REST profiling-run issue_counts).
            counts = HygieneIssue.count_for_run(summary.profiling_run_id)
            hygiene = counts.hygiene_issues
            doc.field(
                "Hygiene issues (confirmed)",
                f"{hygiene.definite + hygiene.likely + hygiene.possible} total "
                f"— {hygiene.definite} definite, {hygiene.likely} likely, {hygiene.possible} possible",
            )
            pii = counts.potential_pii
            if pii.high or pii.moderate:
                doc.field("Potential PII", f"{pii.high} high, {pii.moderate} moderate")
        if summary.dq_score_profiling is not None:
            doc.field("Profiling Score", friendly_score(summary.dq_score_profiling))

    if summary.profiling_run_id:
        breakdown = ProfilingRun.select_table_breakdown(summary.profiling_run_id)
        if breakdown:
            doc.heading(2, "Per-table breakdown")
            headers = ["Table", "Records", "Columns", "Hygiene issues"]
            rows: list[list[object]] = [
                [r.table_name, r.record_ct, r.column_ct, r.anomaly_ct] for r in breakdown
            ]
            if schema_label:
                headers.insert(0, schema_label)
                for row, r in zip(rows, breakdown, strict=True):
                    row.insert(0, r.schema_name)
            doc.table(headers, rows, code=[0, 1] if schema_label else [0])

    warnings = _progress_warnings(summary)
    if warnings:
        doc.heading(2, "Warnings")
        doc.bullets(warnings)
        if summary.profiling_run_id:
            _render_column_errors(doc, summary.profiling_run_id)

    if summary.error_message:
        doc.heading(2, "Error")
        doc.text(target_db_error_text(summary.error_message))

    return doc.render()


def _progress_warnings(run: ProfilingRunSummary) -> list[str]:
    """The run's step warnings, each as ``<step label>: <error>``."""
    return [
        f"{step['label']}: {target_db_error_text(step['error'])}" for step in run.progress or [] if step.get("error")
    ]


def _run_status_label(run: ProfilingRunSummary) -> str:
    if run.status == JobStatus.COMPLETED and _progress_warnings(run):
        return f"{run.status_label} (with warnings)"
    return run.status_label


def _render_column_errors(doc: MdDoc, profiling_run_id: UUID) -> None:
    rows, total = ProfileResult.list_column_errors_for_run(profiling_run_id, limit=_COLUMN_ERRORS_LIMIT)
    if not rows:
        return
    doc.table(
        ["Table", "Column", "Error"],
        [[r.table_name, r.column_name, target_db_error_text(r.query_error)] for r in rows],
        code=[0, 1],
    )
    if total > len(rows):
        doc.text(f"Showing {len(rows)} of {total} columns with errors.")


def _render_pending_profiling_je(doc: MdDoc, je: JobExecution, label: str) -> None:
    status_label = ProfilingRunSummary.STATUS_LABEL.get(je.status, je.status)
    doc.heading(3, f"{label} — {status_label}")
    if je.status == JobStatus.QUEUED:
        doc.text(QUEUED_MESSAGE)
    doc.field("Profiling Run", je.id, code=True)
    if je.job_schedule_id is not None:
        doc.field("Schedule", je.job_schedule_id, code=True)
    doc.field("Submitted", je.created_at)
    doc.field("Started", je.started_at or "—")
    doc.field("Ended", je.completed_at or "In progress")


def _render_provenance_counts(doc: MdDoc, run: ProfilingRunSummary) -> None:
    doc.field("Columns estimated from a sample", run.sampled_column_ct or 0)
    doc.field("Columns with approximate percentiles", run.approximate_percentile_column_ct or 0)


def _render_profiling_run_section(doc: MdDoc, run: ProfilingRunSummary) -> None:
    title = run.table_groups_name or run.profiling_run_id or run.job_execution_id
    doc.heading(2, f"{title} — {_run_status_label(run)}")
    doc.field("Profiling Run", run.job_execution_id, code=True)
    if run.job_schedule_id is not None:
        doc.field("Schedule", run.job_schedule_id, code=True)
    doc.field("Submitted", run.created_at)
    doc.field("Started", run.started_at or "—")
    doc.field("Ended", run.completed_at or "In progress")
    duration = format_run_duration(run.active_seconds, run.status)
    if duration:
        doc.field("Duration", duration)

    if run.table_ct or run.column_ct:
        doc.field("Tables profiled", run.table_ct or 0)
        doc.field("Columns profiled", run.column_ct or 0)
        _render_provenance_counts(doc, run)
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


# ---------------------------------------------------------------------------
# get_column
# ---------------------------------------------------------------------------

# Friendly labels for `std_pattern_match` — mirrors `standardPatternLabels` in
# `ui/components/frontend/js/data_profiling/column_distribution.js`.
_STD_PATTERN_LABELS = {
    "STREET_ADDR": "Street Address",
    "STATE_USA": "State (USA)",
    "PHONE_USA": "Phone (USA)",
    "EMAIL": "Email",
    "ZIP_USA": "Zip Code (USA)",
    "ZIP_US_CA": "Zip Code (US/Canada)",
    "FILE_NAME": "Filename",
    "CREDIT_CARD": "Credit Card",
    "DELIMITED_DATA": "Delimited Data",
    "SSN": "SSN (USA)",
}


def _format_std_pattern(value: str | None) -> str | None:
    if not value:
        return None
    return _STD_PATTERN_LABELS.get(value, value.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Shared helpers for single-column tools (frequent values, patterns)
# ---------------------------------------------------------------------------


def _load_profile_for_column(
    tg: TableGroup,
    table_name: str,
    column_name: str,
    job_execution_id: str | None,
) -> tuple[ProfileResult, ProfilingRun, str | None]:
    """Resolve and load the profile-results row for one column.

    Returns a triple of ``(profile, profiling_run, pii_flag)`` where ``pii_flag`` is
    pulled from ``data_column_chars`` (the source of truth for column-level PII state).
    """
    profiling_run: ProfilingRun | None = None
    if job_execution_id:
        profiling_run = resolve_profiling_run(job_execution_id)
        if profiling_run.table_groups_id != tg.id:
            raise MCPResourceNotAccessible("Profiling run", job_execution_id)
    profile = ProfileResult.get_for_column(
        table_groups_id=tg.id,
        table_name=table_name,
        column_name=column_name,
        profiling_run_id=profiling_run.id if profiling_run else None,
    )
    if profile is None:
        raise MCPResourceNotAccessible("Column profile", f"{table_name}.{column_name}")
    if profiling_run is None:
        profiling_run = ProfilingRun.get(profile.profile_run_id)
        if profiling_run is None:
            raise MCPResourceNotAccessible("Profiling run", str(profile.profile_run_id))
    column_rows = list(DataColumnChars.select_where(
        DataColumnChars.table_groups_id == tg.id,
        DataColumnChars.table_name == table_name,
        DataColumnChars.column_name == column_name,
    ))
    pii_flag = column_rows[0].pii_flag if column_rows else None
    return profile, profiling_run, pii_flag


def _is_pii_redacted_for_caller(tg: TableGroup, pii_flag: str | None) -> bool:
    """Decide whether to redact PII values for this caller + column."""
    if not pii_flag:
        return False
    return not get_project_permissions().has_permission("view_pii", tg.project_code)


@with_database_session
@mcp_permission("catalog")
def get_column(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    table_name: Annotated[str, Field(description="Table name exactly as stored in TestGen (case-sensitive).")],
    column_name: Annotated[str, Field(description="Column name exactly as stored in TestGen (case-sensitive).")],
    job_execution_id: Annotated[
        str | None,
        Field(
            description="UUID of a profiling run, e.g. from `list_profiling_summaries`. When omitted, uses the "
            "column's latest completed run.",
        ),
    ] = None,
) -> str:
    """Get a column's catalog metadata and its profile from one profiling run.

    The profile is type-specific and comes from the column's latest completed profiling run, or from the run given by
    `job_execution_id`. A column that has not been profiled returns its catalog metadata only. When the column has no
    value of its own for a flag or tag, the table's or table group's value is shown, marked as inherited. Tags with no
    value are omitted.
    """
    tg = resolve_table_group(table_group_id)

    profiling_run_id: UUID | None = None
    if job_execution_id:
        profiling_run = resolve_profiling_run(job_execution_id)
        if profiling_run.table_groups_id != tg.id:
            raise MCPResourceNotAccessible("Profiling run", job_execution_id)
        profiling_run_id = profiling_run.id

    detail = DataColumnChars.get_column_detail(
        table_groups_id=tg.id,
        table_name=table_name,
        column_name=column_name,
        profiling_run_id=profiling_run_id,
    )
    if detail is None:
        raise MCPResourceNotAccessible("Column", column_name)

    if detail.profile_run_id is None and job_execution_id:
        raise MCPUserError(
            f"Profiling run `{job_execution_id}` did not include column `{column_name}`."
        )

    # Only a run that finished has measured every column and classified what it measured.
    # Stated as what is allowed rather than what is not, so a status added later is refused
    # until someone decides otherwise.
    if detail.profile_run_id is not None and detail.profile_run_status != JobStatus.COMPLETED:
        _raise_run_not_ready(detail)

    payload = dataclasses.asdict(detail)
    if detail.pii_flag and not get_project_permissions().has_permission("view_pii", tg.project_code):
        mask_profiling_pii(payload, {detail.column_name})

    return _render_column_profile_detail(
        payload, table_group_qualifies_table_refs(tg.id), bool(tg.profile_exclude_xde)
    )


def _raise_run_not_ready(detail: ColumnProfileDetail) -> None:
    """Reject when the resolved profiling run has not finished.

    Surface the run id, status, started/ended timestamps, and `log_message` (Error only)
    in the raised error so the LLM knows what to suggest next.
    """
    je = detail.profile_run_je_id
    status = detail.profile_run_status
    started = detail.profile_run_started_at
    ended = detail.profile_run_ended_at
    started_label = started.strftime("%Y-%m-%d %H:%M UTC") if started else "—"
    ended_label = ended.strftime("%Y-%m-%d %H:%M UTC") if ended else "—"
    status_label = JOB_STATUS_LABEL.get(status, status)
    lines = [
        f"Profiling run `{je}` is in `{status_label}` state — no profile detail available.",
        f"Started: {started_label}. Ended: {ended_label}.",
    ]
    if status == JobStatus.ERROR and detail.profile_run_log_message:
        lines.append(f"Error: {target_db_error_text(detail.profile_run_log_message)}")
    raise MCPUserError("\n".join(lines))


def _render_column_profile_detail(p: dict, qualifies: bool, profiling_excludes_xde: bool) -> str:
    """Render a column's catalog metadata and profile payload as grouped Markdown sections."""
    doc = MdDoc()
    fq_name = _qualified_table_name(p["schema_name"], p["table_name"], qualifies)
    doc.heading(1, f"Column: `{p['column_name']}` in `{fq_name}`")

    general_type = p.get("general_type")

    doc.field("General type", _format_general_type(general_type))
    doc.field("Data type", p["db_data_type"])
    doc.field("Semantic data type", p["functional_data_type"])
    if p.get("datatype_suggestion"):
        doc.field("Suggested data type", p["datatype_suggestion"])
    doc.field("Profiling Score", friendly_score(p.get("dq_score_profiling")))
    doc.field("Testing Score", friendly_score(p.get("dq_score_testing")))

    doc.heading(2, "Catalog metadata")
    if p.get("description"):
        doc.field("Description", _inline_text(p["description"]))
    doc.field("PII", _format_pii(p.get("pii_flag")))
    cde_marker = " (inherited from table)" if p["critical_data_element_inherited"] else ""
    doc.field("Critical data element", f"{'Yes' if p['critical_data_element'] else 'No'}{cde_marker}")
    doc.field("Excluded data element", p["excluded_data_element"])
    render_catalog_tags(doc, parse_catalog_tags(p.get("catalog_tags")))

    doc.heading(2, "Profile")
    if p["profile_run_id"] is None:
        if p["excluded_data_element"] and profiling_excludes_xde:
            doc.text(
                "_This column is an excluded data element and has not been profiled. To profile it, clear its "
                "excluded data element flag with `update_catalog_metadata`._"
            )
        else:
            doc.text(
                "_This column has not been profiled yet. Run profiling for the table group with `run_profiling`._"
            )
        return doc.render()

    doc.field("Profiling Run", p["profile_run_je_id"], code=True)
    doc.field("Profiled at", p["profile_run_started_at"])

    if not p.get("query_error"):
        doc.field("Hygiene issues (confirmed)", p.get("hygiene_issue_count", 0))

        # Type-specific dispatch (T and unknown fall through to common-counts only)
        if general_type == "A":
            _render_alpha_block(doc, p)
        elif general_type == "N":
            _render_numeric_block(doc, p)
        elif general_type == "D":
            _render_date_block(doc, p)
        elif general_type == "B":
            _render_boolean_block(doc, p)
        else:
            _render_unknown_block(doc, p)
    else:
        doc.heading(3, "Profiling Error")
        doc.text(target_db_error_text(p["query_error"]))

    return doc.render()


def _format_general_type(value: str) -> str:
    return GENERAL_TYPE_CODE_TO_LABEL.get(value or "X")


def _provenance_field(doc: MdDoc, profile: ProfileResult, measure: str) -> None:
    """Add a Counts field naming how ``profile``'s value of ``measure`` was taken, when it is not exact."""
    row = {
        "general_type": profile.general_type,
        "sample_ratio": profile.sample_ratio,
        "percentile_method": profile.percentile_method,
        "value_ct": profile.value_ct,
    }
    if provenance := ProfileResult.provenance_label(measure, row):
        doc.field("Counts", provenance)


_UNSET = object()


def _measure_field(doc: MdDoc, p: dict, label: str, measure: str, value: Any = _UNSET) -> None:
    """Add a field labeled ``label`` showing ``value`` (default ``p[measure]``), with ``measure``'s
    provenance label when it is not exact."""
    value = p.get(measure) if value is _UNSET else value
    if value not in (None, PII_REDACTED) and (provenance := ProfileResult.provenance_label(measure, p)):
        # Ahead of a multi-line value, so it does not read as describing only the last line
        value = f"({provenance})\n{value}" if "\n" in str(value) else f"{value} ({provenance})"
    doc.field(label, value)


def _render_counts(doc: MdDoc, p: dict) -> None:
    doc.heading(3, "Counts")
    _measure_field(doc, p, "Row count", "record_ct")
    _measure_field(doc, p, "Value count", "value_ct")
    _measure_field(doc, p, "Distinct values", "distinct_value_ct")
    _measure_field(doc, p, "Null", "null_value_ct")
    _measure_field(doc, p, "Dummy values", "filled_value_ct")
    _measure_field(doc, p, "Zero values", "zero_value_ct")


def _render_alpha_block(doc: MdDoc, p: dict) -> None:
    hide_source_data = mcp_source_data_protected()
    _render_counts(doc, p)
    _measure_field(doc, p, "Zero length", "zero_length_ct")

    doc.heading(3, "Length")
    _measure_field(doc, p, "Minimum length", "min_length")
    _measure_field(doc, p, "Maximum length", "max_length")
    _measure_field(doc, p, "Average length", "avg_length")

    if not hide_source_data:
        doc.heading(3, "Text Range")
        _measure_field(doc, p, "Minimum text", "min_text")
        _measure_field(doc, p, "Maximum text", "max_text")

    doc.heading(3, "Patterns")
    _measure_field(doc, p, "Standard pattern match", "std_pattern_match", _format_std_pattern(p.get("std_pattern_match")))
    _measure_field(doc, p, "Distinct patterns", "distinct_pattern_ct")
    if not hide_source_data:
        _measure_field(doc, p, "Frequent patterns", "frequent_patterns", format_frequent(p.get("frequent_patterns")) or None)
        _measure_field(doc, p, "Frequent values", "frequent_values", format_frequent(p.get("frequent_values")) or None)
    _measure_field(doc, p, "Distinct standard values", "distinct_std_value_ct")

    doc.heading(3, "Case & Composition")
    _measure_field(doc, p, "Upper case", "upper_case_ct")
    _measure_field(doc, p, "Lower case", "lower_case_ct")
    # Mixed case is derived from the upper- and lower-case counts, so it is taken the same way
    _measure_field(doc, p, "Mixed case", "upper_case_ct", p.get("mixed_case_ct"))
    _measure_field(doc, p, "Non-alpha", "non_alpha_ct")
    _measure_field(doc, p, "Includes digits", "includes_digit_ct")
    _measure_field(doc, p, "Numeric values", "numeric_ct")
    _measure_field(doc, p, "Date values", "date_ct")
    _measure_field(doc, p, "Quoted values", "quoted_value_ct")
    _measure_field(doc, p, "Leading spaces", "lead_space_ct")
    _measure_field(doc, p, "Embedded spaces", "embedded_space_ct")
    _measure_field(doc, p, "Average embedded spaces", "avg_embedded_spaces")


def _render_numeric_block(doc: MdDoc, p: dict) -> None:
    hide_source_data = mcp_source_data_protected()
    _render_counts(doc, p)

    doc.heading(3, "Distribution")
    if not hide_source_data:
        _measure_field(doc, p, "Minimum value", "min_value")
        _measure_field(doc, p, "Minimum value > 0", "min_value_over_0")
        _measure_field(doc, p, "Maximum value", "max_value")
    _measure_field(doc, p, "Average value", "avg_value")
    _measure_field(doc, p, "Standard deviation", "stdev_value")

    if not hide_source_data:
        doc.heading(3, "Percentiles")
        _measure_field(doc, p, "25th percentile", "percentile_25")
        _measure_field(doc, p, "Median value", "percentile_50")
        _measure_field(doc, p, "75th percentile", "percentile_75")


def _render_date_block(doc: MdDoc, p: dict) -> None:
    hide_source_data = mcp_source_data_protected()
    _render_counts(doc, p)

    if not hide_source_data:
        doc.heading(3, "Date Range")
        _measure_field(doc, p, "Minimum date", "min_date")
        _measure_field(doc, p, "Maximum date", "max_date")

    doc.heading(3, "Age Buckets")
    _measure_field(doc, p, "Before 1 year", "before_1yr_date_ct")
    _measure_field(doc, p, "Before 5 years", "before_5yr_date_ct")
    _measure_field(doc, p, "Before 20 years", "before_20yr_date_ct")
    _measure_field(doc, p, "Within 1 year", "within_1yr_date_ct")
    _measure_field(doc, p, "Within 1 month", "within_1mo_date_ct")
    _measure_field(doc, p, "Future dates", "future_date_ct")


def _render_boolean_block(doc: MdDoc, p: dict) -> None:
    _render_counts(doc, p)

    doc.heading(3, "Boolean Distribution")
    true_ct = p.get("boolean_true_ct") or 0
    value_ct = p.get("value_ct") or 0
    false_ct = max(value_ct - true_ct, 0)
    doc.field("True count", true_ct)
    doc.field("False count", false_ct)


def _render_unknown_block(doc: MdDoc, p: dict) -> None:
    _render_counts(doc, p)


# ---------------------------------------------------------------------------
# Single-column tools — frequent values and patterns
# ---------------------------------------------------------------------------


@mcp_source_data_only
@with_database_session
@mcp_permission("catalog")
def get_column_frequent_values(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    table_name: Annotated[str, Field(description="Table name exactly as stored in TestGen (case-sensitive).")],
    column_name: Annotated[str, Field(description="Column name exactly as stored in TestGen (case-sensitive).")],
    job_execution_id: Annotated[
        str | None,
        Field(description="UUID of a profiling run. When omitted, uses the column's latest profile run."),
    ] = None,
) -> str:
    """Get the top frequent values for one column from its profile run.
    Each value carries its row count and percentage.

    Profiling captures the top 10 values; when the column has more distinct values, a
    trailing `N other values` row aggregates the remainder.
    """
    tg = resolve_table_group(table_group_id)
    profile, profiling_run, pii_flag = _load_profile_for_column(tg, table_name, column_name, job_execution_id)

    doc = MdDoc()
    doc.heading(1, f"Frequent values: {table_name}.{column_name}")
    doc.field("Table group", tg.id, code=True)
    doc.field("Profiling Run", profiling_run.id, code=True)
    doc.field("Row Count", profile.record_ct)
    doc.field("Distinct values", profile.distinct_value_ct)
    if pii_flag:
        doc.field("PII", _format_pii(pii_flag))

    rows = frequent_entries(profile.frequent_values)
    if not rows:
        doc.text(
            f"_Frequency data not available — profiling recorded none for this column "
            f"(distinct count: {profile.distinct_value_ct})._"
        )
        return doc.render()

    redact = _is_pii_redacted_for_caller(tg, pii_flag)
    record_ct = profile.record_ct or 0
    display_rows: list[list[object]] = []
    for value, count in rows:
        pct = (count / record_ct * 100) if record_ct else None
        display_value = PII_REDACTED if redact else value
        display_rows.append([display_value, count, f"{pct:.2f}%" if pct is not None else None])

    # The remainder carries no values of its own, so it is never redacted.
    if other := (profile.frequent_values or {}).get("other"):
        other_pct = (other["ct"] / record_ct * 100) if record_ct else None
        display_rows.append([
            f"{other['distinct_ct']} other values",
            other["ct"],
            f"{other_pct:.2f}%" if other_pct is not None else None,
        ])

    _provenance_field(doc, profile, "frequent_values")
    doc.heading(2, "Top values")
    doc.table(["Value", "Count", "% of records"], display_rows)
    return doc.render()


@mcp_source_data_only
@with_database_session
@mcp_permission("catalog")
def get_column_patterns(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    table_name: Annotated[str, Field(description="Table name exactly as stored in TestGen (case-sensitive).")],
    column_name: Annotated[str, Field(description="Column name exactly as stored in TestGen (case-sensitive).")],
    job_execution_id: Annotated[
        str | None,
        Field(description="UUID of a profiling run. When omitted, uses the column's latest profile run."),
    ] = None,
) -> str:
    """Get the top character patterns for one string column from its profile run.

    Patterns use shorthand: `A` = uppercase letter, `a` = lowercase letter, `N` = digit;
    every other character (whitespace, punctuation, symbols) appears literally. Examples:
    `Aaaaaaaa` (capitalized word), `NNNN-NN-NN` (ISO-like date), `aaa@aaa.aaa` (email-shaped).
    Profiling captures the top 5 patterns.
    """
    tg = resolve_table_group(table_group_id)
    profile, profiling_run, _ = _load_profile_for_column(tg, table_name, column_name, job_execution_id)

    doc = MdDoc()
    doc.heading(1, f"Character patterns: {table_name}.{column_name}")
    doc.field("Table group", tg.id, code=True)
    doc.field("Profiling Run", profiling_run.id, code=True)
    doc.field("Row Count", profile.record_ct)
    doc.field("Distinct values", profile.distinct_value_ct)

    if profile.general_type and profile.general_type != "A":
        doc.text("_Pattern data not available — column is not a string type._")
        return doc.render()

    rows = frequent_entries(profile.frequent_patterns)
    if not rows:
        doc.text(
            f"_Pattern data not available — profiling recorded none for this column "
            f"(distinct count: {profile.distinct_value_ct})._"
        )
        return doc.render()

    record_ct = profile.record_ct or 0
    display_rows: list[list[object]] = []
    for pattern, count in rows:
        pct = (count / record_ct * 100) if record_ct else None
        display_rows.append([pattern, count, f"{pct:.2f}%" if pct is not None else None])

    _provenance_field(doc, profile, "frequent_patterns")
    doc.heading(2, "Top patterns")
    doc.table(["Pattern", "Count", "% of records"], display_rows, code=[0])
    return doc.render()


# ---------------------------------------------------------------------------
# Cross-scope column-name search
# ---------------------------------------------------------------------------


@with_database_session
@mcp_permission("catalog")
def search_columns(
    pattern: Annotated[str, Field(description="Column-name search pattern. Case-insensitive.")],
    project_code: Annotated[
        str | None,
        Field(description="Optional — scope to one project. Mutually exclusive with `table_group_id`."),
    ] = None,
    table_group_id: Annotated[
        str | None,
        Field(description="Optional — scope to one table group. Mutually exclusive with `project_code`."),
    ] = None,
    limit: Annotated[int, Field(description="Page size (default 100, max 500).")] = 100,
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
) -> str:
    """Search columns by name across one or many projects.
    Bare tokens auto-wrap as `%token%`; an explicit `%` is honored as a wildcard.
    """
    validate_page(page)
    validate_limit(limit, 500)

    if not pattern or not pattern.strip():
        raise MCPUserError("`pattern` is required and cannot be empty.")
    effective_pattern = build_ilike_pattern(pattern)

    if project_code is not None and table_group_id is not None:
        raise MCPUserError("Pass either `project_code` or `table_group_id`, not both.")

    perms = get_project_permissions()
    clauses: list = []

    if table_group_id is not None:
        tg = resolve_table_group(table_group_id)
        clauses.append(DataColumnChars.table_groups_id == tg.id)
        scope_label = f"table group `{table_group_id}`"
    elif project_code is not None:
        perms.verify_access(
            project_code,
            not_found=MCPResourceNotAccessible("Project", project_code),
        )
        clauses.append(TableGroup.project_code == project_code)
        scope_label = f"project `{project_code}`"
    else:
        # The @mcp_permission decorator guarantees ``allowed_codes`` is non-empty by
        # the time the body runs (it raises MCPPermissionDenied otherwise).
        clauses.append(TableGroup.project_code.in_(list(perms.allowed_codes)))
        scope_label = "all accessible projects"

    data, total = DataColumnChars.search_by_name(
        *clauses,
        pattern=effective_pattern,
        page=page,
        limit=limit,
    )

    if not data:
        if page > 1:
            return f"No columns matching `{pattern}` on page {page} (total: {total})."
        return f"No columns matching `{pattern}` in {scope_label}."

    doc = MdDoc()
    doc.heading(1, f"Columns matching `{pattern}` in {scope_label}")

    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    # Per-project match summary when no scope was provided.
    if project_code is None and table_group_id is None:
        summary_rows = DataColumnChars.summarize_matches_by_project(
            *clauses,
            pattern=effective_pattern,
        )
        if summary_rows:
            doc.heading(2, "Matches by project")
            doc.table(
                ["Project", "Matches"],
                [[code_, count] for code_, count in summary_rows],
                code=[0],
            )

    # Hits span table groups, so the schema column carries whatever the matched connections
    # call theirs, and is dropped only when none of them reports one.
    schema_labels = {
        groups_id: schema_label_for_table_group(groups_id)
        for groups_id in dict.fromkeys(hit.table_groups_id for hit in data)
    }
    schema_header = " / ".join(sorted({label for label in schema_labels.values() if label}))

    doc.heading(2, "Columns")
    headers = ["Project", "Table group", "Table", "Column"]
    rows: list[list[object]] = [
        [hit.project_code, hit.table_groups_name, hit.table_name, hit.column_name] for hit in data
    ]
    if schema_header:
        headers.insert(2, schema_header)
        for row, hit in zip(rows, data, strict=True):
            row.insert(2, hit.schema_name if schema_labels[hit.table_groups_id] else None)
    doc.table(headers, rows, code=[0, 1])

    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)
    return doc.render()


@with_database_session
@mcp_permission("catalog")
def generate_create_table_script(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    table_name: Annotated[str, Field(description="Table name exactly as stored in TestGen (case-sensitive).")],
) -> str:
    """Generate a CREATE TABLE script for a profiled table.
    Built from the table's columns and suggested data types.
    """
    tg = resolve_table_group(table_group_id)

    script = build_create_table_script(tg.id, table_name)
    if script is None:
        raise MCPResourceNotAccessible("Table", table_name)

    return MdDoc().code_block(script, language="sql").render()
