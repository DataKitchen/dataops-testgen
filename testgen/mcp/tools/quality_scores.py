from testgen.common.models import with_database_session
from testgen.common.models.scores import (
    ScoreCategory,
    ScoreDefinition,
    ScoreDefinitionCriteria,
)
from testgen.common.models.table_group import TableGroup
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    SCORE_FILTER_FIELD_TO_COLUMN,
    SCORE_GROUP_BY_TO_COLUMN,
    DocGroup,
    ScoreGroupBy,
    ScoreType,
    parse_score_filter_field,
    parse_score_group_by,
    parse_score_type,
    resolve_table_group,
)
from testgen.mcp.tools.markdown import MdDoc
from testgen.utils import friendly_score, friendly_score_impact

_DOC_GROUP = DocGroup.DISCOVER

_VALUE_MAX_LEN = 256
_VALUE_FORBIDDEN_CHARS = frozenset("'\";\\\x00")

# Defensive Python-side cap on grouped output. The category-scores SQL doesn't
# LIMIT, and most valid group_by values produce small bounded result sets
# (≤ ~15 dimensions/domains), but pathological metadata could blow this up.
_ROW_CAP = 100

_COMBINED_LABEL = "Combined Score"
_CDE_LABEL = "CDE Score"


@with_database_session
@mcp_permission("view")
def get_quality_scores(
    *,
    project_code: str | None = None,
    table_group_id: str | None = None,
    group_by: str | None = None,
    score_type: str | None = None,
    filters: list[dict] | None = None,
    include_issue_ct: bool = False,
    include_impact: bool = False,
) -> str:
    """Quality-score rollup with optional grouping and filtering.

    Args:
        project_code: Scope to a single project. Omit to roll across every
            project the caller can view.
        table_group_id: Scope to a single table group, e.g. from
            ``get_data_inventory``. Mutually exclusive with ``project_code``.
        group_by: One of 'Quality Dimension', 'Impact Dimension',
            'Semantic Data Type', 'Table Group', 'Data Location',
            'Data Source', 'Source System', 'Source Process',
            'Business Domain', 'Stakeholder Group', 'Transform Level',
            'Data Product'. Omit for the unfiltered overall score.
        score_type: Narrows which score(s) are reported. Omit (default) to
            show both Combined and CDE; pass 'Combined' to show only the
            Combined Score, or 'CDE' to show only the CDE Score.
        filters: List of {"field": str, "value": str} pairs. Same-field
            filters OR together; different fields AND together. Valid fields
            are the same as ``group_by`` except 'Quality Dimension' and
            'Impact Dimension', which are valid as ``group_by`` only. Filter
            values must not contain quotes, semicolons, or backslashes.
        include_issue_ct: When True, include the count of contributing issues
            (hygiene + test failures).
        include_impact: When True, include the per-category impact on the
            overall score (the percentage contribution to total quality
            loss). Only affects grouped output.
    """
    perms = get_project_permissions()

    if project_code is not None and table_group_id is not None:
        raise MCPUserError(
            "Pass either `project_code` or `table_group_id`, not both."
        )

    parsed_score_type: ScoreType | None = (
        parse_score_type(score_type) if score_type is not None else None
    )
    parsed_group_by: ScoreGroupBy | None = (
        parse_score_group_by(group_by) if group_by is not None else None
    )

    user_filters = _validate_filters(filters)

    if table_group_id is not None:
        table_group = resolve_table_group(table_group_id)
        scope_codes = [table_group.project_code]
        table_group_name = table_group.table_groups_name
    elif project_code is not None:
        perms.verify_access(
            project_code,
            not_found=MCPResourceNotAccessible("Project", project_code),
        )
        scope_codes = [project_code]
        table_group_name = None
    else:
        scope_codes = list(perms.allowed_codes)
        table_group_name = None

    doc = MdDoc()
    doc.heading(1, "Quality Scores")

    if table_group_id is not None:
        doc.text(f"Scope: Table Group `{table_group_name}` (project `{scope_codes[0]}`).")
    elif project_code is not None:
        doc.text(f"Scope: Project `{scope_codes[0]}`.")
    else:
        doc.text(f"Scope: all accessible projects ({len(scope_codes)}).")

    cross_project = project_code is None and table_group_id is None and len(scope_codes) > 1

    for code in scope_codes:
        _render_one_scope(
            doc,
            project_code=code,
            table_group_name=table_group_name,
            group_by=parsed_group_by,
            score_type=parsed_score_type,
            user_filters=user_filters,
            include_issue_ct=include_issue_ct,
            include_impact=include_impact,
            heading=code if cross_project else None,
        )

    return doc.render()


def _validate_filters(filters: list[dict] | None) -> list[dict]:
    """Validate filter dicts and translate ``field`` from user labels to internal DB columns."""
    if not filters:
        return []
    errors: list[str] = []
    cleaned: list[dict] = []
    for i, entry in enumerate(filters):
        if not isinstance(entry, dict):
            errors.append(f"entry {i}: must be a dict with `field` and `value`")
            continue
        field = entry.get("field")
        value = entry.get("value")
        if not field:
            errors.append(f"entry {i}: missing `field`")
            continue
        if value is None or value == "":
            errors.append(f"entry {i} ({field!r}): empty value")
            continue
        try:
            parsed_field = parse_score_filter_field(field)
        except MCPUserError as err:
            errors.append(f"entry {i}: {err}")
            continue
        if not isinstance(value, str):
            errors.append(f"entry {i} ({field!r}): value must be a string")
            continue
        if len(value) > _VALUE_MAX_LEN:
            errors.append(
                f"entry {i} ({field!r}): value too long ({len(value)} > {_VALUE_MAX_LEN})"
            )
            continue
        bad_chars = sorted(set(value) & _VALUE_FORBIDDEN_CHARS)
        if bad_chars:
            errors.append(
                f"entry {i} ({field!r}): value contains forbidden characters {bad_chars}"
            )
            continue
        cleaned.append({"field": SCORE_FILTER_FIELD_TO_COLUMN[parsed_field], "value": value})
    if errors:
        raise MCPUserError("Invalid filters: " + "; ".join(errors))
    return cleaned


def _build_definition(
    *,
    project_code: str,
    table_group_name: str | None,
    group_by: ScoreGroupBy | None,
    score_type: ScoreType | None,
    user_filters: list[dict],
) -> ScoreDefinition:
    definition = ScoreDefinition()
    definition.project_code = project_code
    definition.name = "__mcp_get_quality_scores__"
    # score_type=None enables both; a specific value enables only that one.
    # `as_score_card` derives `cde_only_categories = cde_score and not
    # total_score` — so flag combinations decide whether the category SQL
    # filters by `critical_data_element = true`.
    definition.total_score = score_type is None or score_type is ScoreType.COMBINED
    definition.cde_score = score_type is None or score_type is ScoreType.CDE
    definition.category = (
        ScoreCategory(SCORE_GROUP_BY_TO_COLUMN[group_by]) if group_by is not None else None
    )

    filters: list[dict] = list(user_filters)
    if table_group_name is not None:
        filters.append({"field": "table_groups_name", "value": table_group_name})
    elif not filters:
        # `as_score_card` short-circuits when criteria has no filters
        # (scores.py:292). Mirror the score-explorer UI's pattern: a
        # scorecard always carries at least one filter, typically
        # `table_groups_name`. For the unfiltered project-wide case,
        # enumerate every table group in the project so the criteria
        # still narrows by project_code (added by `_get_raw_query_filters`)
        # and covers all table groups.
        tg_names = [
            tg.table_groups_name
            for tg in TableGroup.select_minimal_where(
                TableGroup.project_code == project_code,
            )
        ]
        if tg_names:
            filters.extend(
                {"field": "table_groups_name", "value": name} for name in tg_names
            )

    definition.criteria = ScoreDefinitionCriteria.from_filters(
        filters, group_by_field=True,
    )
    return definition


def _render_one_scope(
    doc: MdDoc,
    *,
    project_code: str,
    table_group_name: str | None,
    group_by: ScoreGroupBy | None,
    score_type: ScoreType | None,
    user_filters: list[dict],
    include_issue_ct: bool,
    include_impact: bool,
    heading: str | None,
) -> None:
    if heading is not None:
        doc.heading(2, f"Project `{heading}`")

    definition = _build_definition(
        project_code=project_code,
        table_group_name=table_group_name,
        group_by=group_by,
        score_type=score_type,
        user_filters=user_filters,
    )

    show_combined = score_type is None or score_type is ScoreType.COMBINED
    show_cde = score_type is None or score_type is ScoreType.CDE

    card = definition.as_score_card()
    if show_combined:
        doc.field(_COMBINED_LABEL, friendly_score(card.get("score")))
    if show_cde:
        doc.field(_CDE_LABEL, friendly_score(card.get("cde_score")))

    if include_issue_ct and group_by is None:
        doc.field("Issue Count", definition.get_overall_issue_ct())

    if group_by is None:
        return

    group_by_column = SCORE_GROUP_BY_TO_COLUMN[group_by]

    # Per-category data — score, impact, issue_ct — comes from
    # get_score_card_breakdown. One call per enabled score type, since each
    # filters different rows (Combined includes all data points; CDE filters
    # to critical_data_element=true).
    combined_rows: dict[str, dict] = {}
    cde_rows: dict[str, dict] = {}
    if show_combined:
        for r in definition.get_score_card_breakdown("score", group_by_column):
            label = r.get(group_by_column)
            if label is not None:
                combined_rows[label] = r
    if show_cde:
        for r in definition.get_score_card_breakdown("cde_score", group_by_column):
            label = r.get(group_by_column)
            if label is not None:
                cde_rows[label] = r

    all_labels = set(combined_rows) | set(cde_rows)
    if not all_labels:
        doc.text("_No category data._")
        return

    # Worst score first. Sort by primary column (Combined if shown, else CDE).
    def _sort_key(label: str) -> float:
        primary = combined_rows if show_combined else cde_rows
        score = (primary.get(label) or {}).get("score")
        return score if score is not None else 1.0

    sorted_labels = sorted(all_labels, key=_sort_key)
    total_rows = len(sorted_labels)
    capped = sorted_labels[:_ROW_CAP]

    both_shown = show_combined and show_cde
    combined_issue_header = "Issue Count (Combined)" if both_shown else "Issue Count"
    cde_issue_header = "Issue Count (CDE)" if both_shown else "Issue Count"

    headers: list[str] = [group_by.value]
    if show_combined:
        headers.append(_COMBINED_LABEL)
        if include_impact:
            headers.append("Impact on Combined Score")
        if include_issue_ct:
            headers.append(combined_issue_header)
    if show_cde:
        headers.append(_CDE_LABEL)
        if include_impact:
            headers.append("Impact on CDE Score")
        if include_issue_ct:
            headers.append(cde_issue_header)

    md_rows: list[list[object]] = []
    for label in capped:
        cells: list[object] = [label]
        c_row = combined_rows.get(label) or {}
        d_row = cde_rows.get(label) or {}
        if show_combined:
            cells.append(friendly_score(c_row.get("score")))
            if include_impact:
                cells.append(_format_impact(c_row.get("impact")))
            if include_issue_ct:
                cells.append(c_row.get("issue_ct") if c_row else None)
        if show_cde:
            cells.append(friendly_score(d_row.get("score")))
            if include_impact:
                cells.append(_format_impact(d_row.get("impact")))
            if include_issue_ct:
                cells.append(d_row.get("issue_ct") if d_row else None)
        md_rows.append(cells)
    doc.table(headers, md_rows)

    if total_rows > _ROW_CAP:
        doc.text(f"_Showing top {_ROW_CAP} of {total_rows} rows by lowest score._")


def _format_impact(value: float | None) -> str | None:
    # Pass None through so MdDoc renders an em-dash for missing data
    # (friendly_score_impact returns the literal "-" for None/0, which
    # mismatches the score column's em-dash treatment).
    if value is None:
        return None
    return friendly_score_impact(value)
