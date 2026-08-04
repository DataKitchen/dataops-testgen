from collections import defaultdict

from testgen.commands.run_refresh_score_cards_results import save_and_refresh_score_definition
from testgen.common.models import with_database_session
from testgen.common.models.scores import (
    ScoreCategory,
    ScoreDefinition,
    ScoreDefinitionBreakdownItem,
    ScoreDefinitionCriteria,
    ScoreDefinitionFilter,
)
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    SCORE_CHAIN_LEAF_TO_COLUMN,
    SCORE_FILTER_FIELD_TO_COLUMN,
    SCORE_GROUP_BY_TO_COLUMN,
    DocGroup,
    ScoreChainLeafField,
    ScoreFilterField,
    ScoreGroupBy,
    ScoreType,
    format_page_footer,
    format_page_info,
    parse_category,
    parse_score_group_by,
    parse_score_type,
    resolve_scorecard,
    resolve_table_group,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc
from testgen.utils import friendly_score, friendly_score_impact

_DOC_GROUP = DocGroup.SCORING

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100

_VALUE_MAX_LEN = 256
_VALUE_FORBIDDEN_CHARS = frozenset("'\";\\\x00")

# Defensive Python-side cap on grouped output. The category-scores SQL doesn't
# LIMIT, and most valid group_by values produce small bounded result sets
# (≤ ~15 dimensions/domains), but pathological metadata could blow this up.
_ROW_CAP = 100

_TOTAL_LABEL = "Total Score"
_CDE_LABEL = "CDE Score"

_COLUMN_TO_LABEL: dict[str, str] = {
    column: group_by.value for group_by, column in SCORE_GROUP_BY_TO_COLUMN.items()
}
# Chain-only fields (mode 2): not exposed as standalone filter fields but valid
# as the leaves of a `table_groups_name → table_name → column_name` chain.
_COLUMN_TO_LABEL["table_name"] = "Table"
_COLUMN_TO_LABEL["column_name"] = "Column"


_CHAIN_ROOT_FIELD = ScoreFilterField.TABLE_GROUP.value  # "Table Group"
_CHAIN_LEAF_FIELDS = tuple(f.value for f in ScoreChainLeafField)  # ("Table", "Column")


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

    Returns overall Total, CDE, Profiling, and Testing scores by default,
    plus an optional breakdown table when ``group_by`` is set. Scope is
    project-wide unless ``project_code`` or ``table_group_id`` narrows it.

    **Filters.** Each filter is
    ``{"field": "...", "value": "...", "others"?: [...]}``. Same-field values
    OR together; different fields AND together. Valid flat fields:
    ``"Table Group"``, ``"Data Location"``, ``"Data Source"``,
    ``"Source System"``, ``"Source Process"``, ``"Business Domain"``,
    ``"Stakeholder Group"``, ``"Transform Level"``, ``"Semantic Data Type"``,
    ``"Data Product"``, ``"Data Classification"``. To target specific tables or columns, chain a
    ``"Table Group"`` filter via ``others`` into ``"Table"`` (optionally
    then ``"Column"``); sibling chains OR. ``"Impact Dimension"`` and
    ``"Quality Dimension"`` are valid as ``group_by`` only, not as filter
    fields. Filter values must not contain quotes, semicolons, or
    backslashes. ``table_group_id`` cannot be combined with chained
    filters — put ``"Table Group"`` in the chain root instead.

    Args:
        project_code: Scope to a project. Mutually exclusive with
            ``table_group_id``. Omit both to roll across every visible
            project.
        table_group_id: Scope to a table group, e.g. from
            ``get_data_inventory``.
        group_by: Break overall scores out by one of: ``"Impact Dimension"``,
            ``"Quality Dimension"``, ``"Semantic Data Type"``,
            ``"Table Group"``, ``"Data Location"``, ``"Data Source"``,
            ``"Source System"``, ``"Source Process"``, ``"Business Domain"``,
            ``"Stakeholder Group"``, ``"Transform Level"``,
            ``"Data Product"``, ``"Data Classification"``.
        score_type: Narrow returned scores. Omit to show all four (Total,
            CDE, Profiling, Testing); pass ``"Total"`` for Total + Profiling
            + Testing, or ``"CDE"`` for CDE alone.
        filters: List of filter entries. See **Filters** above for shape.
        include_issue_ct: Include the count of contributing issues
            (hygiene + test failures).
        include_impact: Include the per-category percentage impact on the
            overall score. Only affects grouped output.
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

    user_filters, group_by_field = _validate_filters(filters, allow_empty=True)

    if table_group_id is not None and not group_by_field:
        raise MCPUserError(
            "`table_group_id` cannot be combined with chained filters — "
            "put `Table Group` in the chain root instead."
        )

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
            group_by_field=group_by_field,
            include_issue_ct=include_issue_ct,
            include_impact=include_impact,
            heading=code if cross_project else None,
        )

    return doc.render()


def _build_definition(
    *,
    project_code: str,
    table_group_name: str | None,
    group_by: ScoreGroupBy | None,
    score_type: ScoreType | None,
    user_filters: list[dict],
    group_by_field: bool,
) -> ScoreDefinition:
    definition = ScoreDefinition()
    definition.project_code = project_code
    definition.name = "__mcp_get_quality_scores__"
    # score_type=None enables both; a specific value enables only that one.
    # `as_score_card` derives `cde_only_categories = cde_score and not
    # total_score` — so flag combinations decide whether the category SQL
    # filters by `critical_data_element = true`.
    definition.total_score = score_type is None or score_type is ScoreType.TOTAL
    definition.cde_score = score_type is None or score_type is ScoreType.CDE
    definition.category = (
        ScoreCategory(SCORE_GROUP_BY_TO_COLUMN[group_by]) if group_by is not None else None
    )

    filters: list[dict] = list(user_filters)
    if table_group_name is not None:
        filters.append({"field": "table_groups_name", "value": table_group_name})

    definition.criteria = ScoreDefinitionCriteria.from_filters(
        filters, group_by_field=group_by_field,
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
    group_by_field: bool,
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
        group_by_field=group_by_field,
    )

    show_total = score_type is None or score_type is ScoreType.TOTAL
    show_cde = score_type is None or score_type is ScoreType.CDE

    card = definition.as_score_card()
    if show_total:
        doc.field(_TOTAL_LABEL, friendly_score(card.get("score")))
    if show_cde:
        doc.field(_CDE_LABEL, friendly_score(card.get("cde_score")))
    if show_total:
        doc.field("Profiling Score", friendly_score(card.get("profiling_score")))
        doc.field("Testing Score", friendly_score(card.get("testing_score")))

    if include_issue_ct and group_by is None:
        doc.field("Issue Count", definition.get_overall_issue_ct())

    if group_by is None:
        return

    group_by_column = SCORE_GROUP_BY_TO_COLUMN[group_by]

    # Per-category data — score, impact, issue_ct — comes from
    # get_score_card_breakdown. One call per enabled score type, since each
    # filters different rows (Total includes all data points; CDE filters
    # to critical_data_element=true).
    total_rows: dict[str, dict] = {}
    cde_rows: dict[str, dict] = {}
    if show_total:
        for r in definition.get_score_card_breakdown("score", group_by_column):
            label = r.get(group_by_column)
            if label is not None:
                total_rows[label] = r
    if show_cde:
        for r in definition.get_score_card_breakdown("cde_score", group_by_column):
            label = r.get(group_by_column)
            if label is not None:
                cde_rows[label] = r

    all_labels = set(total_rows) | set(cde_rows)
    if not all_labels:
        if user_filters:
            doc.text("_Filter matched no data._")
        else:
            doc.text("_No category data._")
        return

    # Worst score first. Sort by primary column (Total if shown, else CDE).
    def _sort_key(label: str) -> float:
        primary = total_rows if show_total else cde_rows
        score = (primary.get(label) or {}).get("score")
        return score if score is not None else 1.0

    sorted_labels = sorted(all_labels, key=_sort_key)
    row_count = len(sorted_labels)
    capped = sorted_labels[:_ROW_CAP]

    both_shown = show_total and show_cde
    total_issue_header = "Issue Count (Total)" if both_shown else "Issue Count"
    cde_issue_header = "Issue Count (CDE)" if both_shown else "Issue Count"

    headers: list[str] = [group_by.value]
    if show_total:
        headers.append(_TOTAL_LABEL)
        if include_impact:
            headers.append("Impact on Total Score")
        if include_issue_ct:
            headers.append(total_issue_header)
    if show_cde:
        headers.append(_CDE_LABEL)
        if include_impact:
            headers.append("Impact on CDE Score")
        if include_issue_ct:
            headers.append(cde_issue_header)

    md_rows: list[list[object]] = []
    for label in capped:
        cells: list[object] = [label]
        c_row = total_rows.get(label) or {}
        d_row = cde_rows.get(label) or {}
        if show_total:
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

    if row_count > _ROW_CAP:
        doc.text(f"_Showing top {_ROW_CAP} of {row_count} rows by lowest score._")


@with_database_session
@mcp_permission("view")
def list_scorecards(
    project_code: str,
    page: int = 1,
    limit: int = _DEFAULT_LIMIT,
) -> str:
    """List the scorecards defined in a project.

    Args:
        project_code: Project to list scorecards for.
        page: Page number, starting at 1.
        limit: Page size (max 100).
    """
    validate_page(page)
    validate_limit(limit, _MAX_LIMIT)

    perms = get_project_permissions()
    perms.verify_access(
        project_code,
        not_found=MCPResourceNotAccessible("Project", project_code),
    )

    definitions, total = ScoreDefinition.list_for_project(
        project_code, page=page, limit=limit,
    )

    doc = MdDoc()
    doc.heading(1, f"Scorecards in Project `{project_code}`")

    page_info = format_page_info(total, page, limit)
    if page_info:
        doc.text(page_info)

    if not definitions:
        if page > 1:
            doc.text(f"_No scorecards on page {page} (total: {total})._")
        else:
            doc.text("_No scorecards configured._")
        return doc.render()

    for definition in definitions:
        doc.heading(2, f"{definition.name} (id: `{definition.id}`)")
        card = definition.as_cached_score_card()
        if definition.total_score:
            doc.field(_TOTAL_LABEL, friendly_score(card.get("score")))
        if definition.cde_score:
            doc.field(_CDE_LABEL, friendly_score(card.get("cde_score")))
        if definition.total_score:
            doc.field("Profiling Score", friendly_score(card.get("profiling_score")))
            doc.field("Testing Score", friendly_score(card.get("testing_score")))
        if definition.category is not None:
            doc.field("Category", _column_label(definition.category.value))
        doc.field("Filters", _format_criteria_summary(definition.criteria))

    footer = format_page_footer(total, page, limit)
    if footer:
        doc.text(footer)

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_scorecard(scorecard_id: str) -> str:
    """Get a scorecard with its current scores and per-category breakdown.

    Args:
        scorecard_id: UUID returned by ``list_scorecards`` or ``get_data_inventory``.
    """
    definition = resolve_scorecard(scorecard_id)
    card = definition.as_cached_score_card()

    doc = MdDoc()
    doc.heading(1, f"Scorecard: {definition.name}")

    doc.field("ID", definition.id, code=True)
    doc.field("Project", definition.project_code, code=True)
    if definition.total_score:
        doc.field(_TOTAL_LABEL, friendly_score(card.get("score")))
    if definition.cde_score:
        doc.field(_CDE_LABEL, friendly_score(card.get("cde_score")))
    if definition.total_score:
        doc.field("Profiling Score", friendly_score(card.get("profiling_score")))
        doc.field("Testing Score", friendly_score(card.get("testing_score")))
    if definition.category is not None:
        doc.field("Category", _column_label(definition.category.value))
    doc.field("Filters", _format_criteria_summary(definition.criteria))

    if definition.category is not None:
        _render_breakdown(doc, definition)

    return doc.render()


def _render_breakdown(doc: MdDoc, definition: ScoreDefinition) -> None:
    """Render the per-category breakdown table for an enabled score_type pair.

    Total and CDE rows are merged by label so the same category value shows
    on one line with both score_types. Sorted by primary-score-type impact
    desc; capped at ``_ROW_CAP`` rows with a truncation footer when exceeded.
    """
    category_column = definition.category.value
    category_label = _column_label(category_column)
    doc.heading(2, f"Breakdown by {category_label}")

    show_total = definition.total_score
    show_cde = definition.cde_score

    total_rows: dict[str, dict] = {}
    cde_rows: dict[str, dict] = {}
    if show_total:
        for item in ScoreDefinitionBreakdownItem.filter(
            definition_id=definition.id,
            category=category_column,
            score_type="score",
        ):
            row = item.to_dict()
            label = _row_label(row, category_column)
            if label is not None:
                total_rows[label] = row
    if show_cde:
        for item in ScoreDefinitionBreakdownItem.filter(
            definition_id=definition.id,
            category=category_column,
            score_type="cde_score",
        ):
            row = item.to_dict()
            label = _row_label(row, category_column)
            if label is not None:
                cde_rows[label] = row

    all_labels = set(total_rows) | set(cde_rows)
    if not all_labels:
        doc.text("_No breakdown data._")
        return

    primary = total_rows if show_total else cde_rows

    def _sort_key(label: str) -> float:
        impact = (primary.get(label) or {}).get("impact")
        return impact if impact is not None else 0.0

    # Highest impact first — same ordering as the cached rows from the model.
    sorted_labels = sorted(all_labels, key=_sort_key, reverse=True)
    row_count = len(sorted_labels)
    capped = sorted_labels[:_ROW_CAP]

    both_shown = show_total and show_cde
    total_issue_header = "Issue Count (Total)" if both_shown else "Issue Count"
    cde_issue_header = "Issue Count (CDE)" if both_shown else "Issue Count"

    headers: list[str] = [category_label]
    if show_total:
        headers.extend([_TOTAL_LABEL, "Impact on Total Score", total_issue_header])
    if show_cde:
        headers.extend([_CDE_LABEL, "Impact on CDE Score", cde_issue_header])

    md_rows: list[list[object]] = []
    for label in capped:
        cells: list[object] = [label]
        c_row = total_rows.get(label) or {}
        d_row = cde_rows.get(label) or {}
        if show_total:
            cells.append(friendly_score(c_row.get("score")))
            cells.append(_format_impact(c_row.get("impact")))
            cells.append(c_row.get("issue_ct") if c_row else None)
        if show_cde:
            cells.append(friendly_score(d_row.get("score")))
            cells.append(_format_impact(d_row.get("impact")))
            cells.append(d_row.get("issue_ct") if d_row else None)
        md_rows.append(cells)
    doc.table(headers, md_rows)

    if row_count > _ROW_CAP:
        doc.text(f"_Showing top {_ROW_CAP} of {row_count} rows by highest impact._")


@with_database_session
@mcp_permission("edit")
def create_scorecard(
    project_code: str,
    name: str,
    filters: list[dict],
    *,
    category: str | None = None,
    show_total_score: bool = True,
    show_cde_score: bool = False,
) -> str:
    """Create a scorecard in a project.

    **Filters.** At least one filter is required. Each entry is
    ``{"field": "...", "value": "...", "others"?: [...]}``. Same-field values
    OR together; different fields AND together. Valid flat fields:
    ``"Table Group"``, ``"Data Location"``, ``"Data Source"``,
    ``"Source System"``, ``"Source Process"``, ``"Business Domain"``,
    ``"Stakeholder Group"``, ``"Transform Level"``, ``"Semantic Data Type"``,
    ``"Data Product"``, ``"Data Classification"``. To target specific tables or columns, chain a
    ``"Table Group"`` filter via ``others`` into ``"Table"`` (optionally
    then ``"Column"``); sibling chains OR.

    Args:
        project_code: Project that will own the scorecard.
        name: Scorecard name. Must be non-empty.
        filters: List of filter entries. See **Filters** above for shape.
        category: Category for per-bucket breakdown. One of
            ``"Quality Dimension"``, ``"Impact Dimension"``,
            ``"Data Source"``, ``"Business Domain"``, ``"Stakeholder Group"``,
            ``"Table Group"``, ``"Transform Level"``, ``"Data Location"``,
            ``"Source System"``, ``"Source Process"``, ``"Data Product"``,
            ``"Data Classification"``.
        show_total_score: Whether the scorecard exposes the Total Score.
        show_cde_score: Whether the scorecard exposes the CDE Score.
    """
    perms = get_project_permissions()
    perms.verify_access(
        project_code,
        not_found=MCPResourceNotAccessible("Project", project_code),
    )

    if not name.strip():
        raise MCPUserError("`name` must be non-empty.")

    parsed_filters, group_by_field = _validate_filters(filters)
    category_value = parse_category(category) if category is not None else None

    definition = ScoreDefinition()
    definition.project_code = project_code
    definition.name = name
    definition.total_score = show_total_score
    definition.cde_score = show_cde_score
    definition.category = category_value
    definition.criteria = ScoreDefinitionCriteria.from_filters(
        parsed_filters,
        group_by_field=group_by_field,
    )

    save_and_refresh_score_definition(definition, is_new=True)

    doc = MdDoc()
    doc.heading(1, f"Scorecard `{definition.name}` created")
    doc.field("ID", definition.id, code=True)
    doc.field("Project", definition.project_code, code=True)
    doc.field(_TOTAL_LABEL, "Yes" if show_total_score else "No")
    doc.field(_CDE_LABEL, "Yes" if show_cde_score else "No")
    if category_value is not None:
        doc.field("Category", _column_label(category_value.value))
    doc.field("Filters", _format_criteria_summary(definition.criteria))
    return doc.render()


@with_database_session
@mcp_permission("edit")
def update_scorecard(
    scorecard_id: str,
    *,
    name: str | None = None,
    show_total_score: bool | None = None,
    show_cde_score: bool | None = None,
    category: str | None = None,
    filters: list[dict] | None = None,
) -> str:
    """Update fields on an existing scorecard. Pass only the fields to change.

    **Filters.** When supplied, ``filters`` replaces the scorecard's filters
    wholesale and at least one entry is required. Each entry is
    ``{"field": "...", "value": "...", "others"?: [...]}``. Same-field values
    OR together; different fields AND together. Valid flat fields:
    ``"Table Group"``, ``"Data Location"``, ``"Data Source"``,
    ``"Source System"``, ``"Source Process"``, ``"Business Domain"``,
    ``"Stakeholder Group"``, ``"Transform Level"``, ``"Semantic Data Type"``,
    ``"Data Product"``, ``"Data Classification"``. To target specific tables or columns, chain a
    ``"Table Group"`` filter via ``others`` into ``"Table"`` (optionally
    then ``"Column"``); sibling chains OR.

    Args:
        scorecard_id: UUID returned by ``list_scorecards`` or
            ``get_data_inventory``.
        name: New scorecard name. Must be non-empty when supplied.
        show_total_score: Whether the scorecard exposes the Total Score.
        show_cde_score: Whether the scorecard exposes the CDE Score.
        category: Category for per-bucket breakdown. One of
            ``"Quality Dimension"``, ``"Impact Dimension"``,
            ``"Data Source"``, ``"Business Domain"``, ``"Stakeholder Group"``,
            ``"Table Group"``, ``"Transform Level"``, ``"Data Location"``,
            ``"Source System"``, ``"Source Process"``, ``"Data Product"``,
            ``"Data Classification"``.
            Pass ``""`` to clear an existing category.
        filters: List of filter entries. See **Filters** above for shape.
    """
    definition = resolve_scorecard(scorecard_id)

    new_category: ScoreCategory | None = None
    clear_category = category == ""
    if category is not None and not clear_category:
        new_category = parse_category(category)

    parsed_filters: list[dict] | None = None
    group_by_field: bool | None = None
    if filters is not None:
        parsed_filters, group_by_field = _validate_filters(filters)

    pending: dict = {}
    if name is not None:
        if not name.strip():
            raise MCPUserError("`name` must be non-empty.")
        pending["name"] = name
    if show_total_score is not None:
        pending["total_score"] = show_total_score
    if show_cde_score is not None:
        pending["cde_score"] = show_cde_score
    if new_category is not None:
        pending["category"] = new_category
    elif clear_category:
        pending["category"] = None
    if parsed_filters is not None:
        pending["criteria"] = ScoreDefinitionCriteria.from_filters(
            parsed_filters,
            group_by_field=group_by_field,
        )

    if not pending:
        raise MCPUserError("No fields supplied to update.")

    before = _snapshot_for_diff(definition, pending)
    for attr, value in pending.items():
        setattr(definition, attr, value)
    after = _snapshot_for_diff(definition, pending)

    save_and_refresh_score_definition(definition, is_new=False)

    doc = MdDoc()
    doc.heading(1, f"Scorecard `{definition.name}` updated")
    doc.field("ID", definition.id, code=True)
    doc.field("Project", definition.project_code, code=True)
    rows = [
        [_DIFF_LABELS[attr], before[attr], after[attr]]
        for attr in pending
    ]
    doc.table(["Field", "Before", "After"], rows, code=[0])
    return doc.render()


_DIFF_LABELS: dict[str, str] = {
    "name": "Name",
    "total_score": _TOTAL_LABEL,
    "cde_score": _CDE_LABEL,
    "category": "Category",
    "criteria": "Filters",
}


def _snapshot_for_diff(definition: ScoreDefinition, attrs: dict) -> dict[str, str | None]:
    """Render display-form values for each attr being changed."""
    snapshot: dict[str, str | None] = {}
    for attr in attrs:
        value = getattr(definition, attr, None)
        if attr == "category":
            snapshot[attr] = _column_label(value.value) if value is not None else None
        elif attr == "criteria":
            snapshot[attr] = _format_criteria_summary(value)
        elif isinstance(value, bool):
            snapshot[attr] = "Yes" if value else "No"
        else:
            snapshot[attr] = value if value is not None else None
    return snapshot


@with_database_session
@mcp_permission("edit")
def delete_scorecard(scorecard_id: str) -> str:
    """Delete a scorecard.

    Args:
        scorecard_id: UUID returned by ``list_scorecards`` or ``get_data_inventory``.
    """
    definition = resolve_scorecard(scorecard_id)
    name = definition.name
    project_code = definition.project_code
    deleted_id = definition.id

    definition.delete()

    doc = MdDoc()
    doc.heading(1, f"Scorecard `{name}` deleted")
    doc.field("ID", deleted_id, code=True)
    doc.field("Project", project_code, code=True)
    return doc.render()

def _filter_value_errors(value: object, field: str) -> list[str]:
    """Return error strings for an unsafe filter value (empty list if safe).

    Catches non-string types, over-length values, and forbidden characters
    that would enable SQL injection via ``ScoreDefinitionCriteria.get_as_sql``.
    Does not check for empty/missing values — callers handle that separately.
    """
    if not isinstance(value, str):
        return [f"({field!r}): value must be a string"]
    errors: list[str] = []
    if len(value) > _VALUE_MAX_LEN:
        errors.append(f"({field!r}): value too long ({len(value)} > {_VALUE_MAX_LEN})")
    bad_chars = sorted(set(value) & _VALUE_FORBIDDEN_CHARS)
    if bad_chars:
        errors.append(f"({field!r}): value contains forbidden characters {bad_chars}")
    return errors


def _validate_filters(
    raw_filters: list[dict] | None, *, allow_empty: bool = False,
) -> tuple[list[dict], bool]:
    """Validate user-supplied filter shape and translate to column-form storage.

    Returns ``(parsed_filters, group_by_field)``. Input ``field`` values are
    display-form (e.g. ``"Table Group"``, ``"Data Source"``, ``"Table"``,
    ``"Column"``); the returned dicts use the underlying DB column names
    (e.g. ``"table_groups_name"``, ``"table_name"``).

    Two storage modes (selectable per call, not mutually exclusive across
    callers):

    * Mode 1 (flat, ``group_by_field=True``): every filter is a single
      ``(field, value)`` pair using one of the values from ``ScoreFilterField``.
    * Mode 2 (chained, ``group_by_field=False``): each chained filter roots at
      ``"Table Group"`` and chains only into ``"Table"`` then ``"Column"``. A
      flat ``"Table Group"`` filter is also valid here.

    Errors are collected across every offending entry and reported in one
    ``MCPUserError`` so callers see every problem at once rather than chasing
    one fix at a time.

    When ``allow_empty=True``, ``None`` / ``[]`` short-circuits to
    ``([], True)``. With the default ``allow_empty=False``, empty input raises.
    """
    if not raw_filters:
        if allow_empty:
            return [], True
        raise MCPUserError("At least one filter is required.")

    errors: list[str] = []
    for index, filter_ in enumerate(raw_filters):
        if not filter_.get("field") or not filter_.get("value"):
            errors.append(
                f"filters[{index}] must have non-empty `field` and `value`."
            )
            continue
        errors.extend(
            f"filters[{index}] {err}"
            for err in _filter_value_errors(filter_["value"], filter_["field"])
        )

    valid_mode_1_fields = {f.value for f in ScoreFilterField}
    has_chain = any(
        isinstance(filter_, dict) and filter_.get("others")
        for filter_ in raw_filters
    )

    if not has_chain:
        parsed: list[dict] = []
        for index, filter_ in enumerate(raw_filters):
            if not filter_.get("field") or not filter_.get("value"):
                continue
            field = filter_["field"]
            if field not in valid_mode_1_fields:
                valid = ", ".join(sorted(valid_mode_1_fields))
                errors.append(
                    f"filters[{index}]: `{field}` is not a valid scorecard filter "
                    f"field. To target specific tables or columns, chain a "
                    f"`{_CHAIN_ROOT_FIELD}` filter with `others`: "
                    f'[{{"field": "Table", "value": "..."}}]. '
                    f"Valid flat fields: {valid}."
                )
                continue
            parsed.append({
                "field": SCORE_FILTER_FIELD_TO_COLUMN[ScoreFilterField(field)],
                "value": filter_["value"],
            })
        if errors:
            raise MCPUserError("Invalid filters: " + "; ".join(errors))
        return parsed, True

    parsed_chained: list[dict] = []
    for index, filter_ in enumerate(raw_filters):
        if not filter_.get("field") or not filter_.get("value"):
            continue
        field = filter_["field"]
        others = filter_.get("others") or []
        if others and field != _CHAIN_ROOT_FIELD:
            errors.append(
                f"filters[{index}]: chained filters must root at "
                f"`{_CHAIN_ROOT_FIELD}`, got `{field}`."
            )
            continue
        if not others and field != _CHAIN_ROOT_FIELD:
            errors.append(
                f"filters[{index}]: when any filter chains tables/columns, "
                f"all filters must root at `{_CHAIN_ROOT_FIELD}`. Got `{field}`."
            )
            continue

        translated_others: list[dict] = []
        chain_errors = False
        for chain_index, chain in enumerate(others):
            if not chain.get("field") or not chain.get("value"):
                errors.append(
                    f"filters[{index}].others[{chain_index}] must have "
                    f"non-empty `field` and `value`."
                )
                chain_errors = True
                continue
            chain_field = chain["field"]
            if chain_field not in _CHAIN_LEAF_FIELDS:
                errors.append(
                    f"filters[{index}].others[{chain_index}]: `{chain_field}` "
                    f"is not a valid chain field. Chains may only descend into "
                    f"{' or '.join(f'`{f}`' for f in _CHAIN_LEAF_FIELDS)}."
                )
                chain_errors = True
                continue
            value_errors = _filter_value_errors(chain["value"], chain_field)
            if value_errors:
                errors.extend(
                    f"filters[{index}].others[{chain_index}] {err}"
                    for err in value_errors
                )
                chain_errors = True
                continue
            translated_others.append({
                "field": SCORE_CHAIN_LEAF_TO_COLUMN[ScoreChainLeafField(chain_field)],
                "value": chain["value"],
            })

        chain_field_values = [c.get("field") for c in others]
        if chain_field_values == [ScoreChainLeafField.COLUMN.value]:
            errors.append(
                f"filters[{index}]: a `Column` chain requires a `Table` step before it."
            )
            continue
        if ScoreChainLeafField.COLUMN.value in chain_field_values[:-1]:
            errors.append(
                f"filters[{index}]: `Column` must be the final chain step."
            )
            continue

        if chain_errors:
            continue

        parsed_chained.append({
            "field": SCORE_FILTER_FIELD_TO_COLUMN[ScoreFilterField.TABLE_GROUP],
            "value": filter_["value"],
            "others": translated_others,
        })

    if errors:
        raise MCPUserError("Invalid filters: " + "; ".join(errors))
    return parsed_chained, False


def _row_label(row: dict, category_column: str) -> str | None:
    """Compose the display label for a breakdown row.

    For ``column_name`` breakdowns, prefix with the table name so columns with
    the same name from different tables don't collapse into one bucket. NULL
    category values (e.g. table-scope tests with no column_name) return
    ``None`` so the row is skipped — matches ``get_quality_scores``.
    """
    if category_column == "column_name":
        table = row.get("table_name")
        column = row.get("column_name")
        if column is None:
            return None
        return f"{table}.{column}" if table else column
    return row.get(category_column)


def _format_impact(value: float | None) -> str | None:
    # Pass None through so MdDoc renders an em-dash for missing data —
    # friendly_score_impact returns the literal "-" for None/0, which
    # mismatches the score column's em-dash treatment.
    if value is None:
        return None
    return friendly_score_impact(value)


def _format_criteria_summary(criteria: ScoreDefinitionCriteria | None) -> str:
    """Human-readable summary of a scorecard's criteria.

    Two render modes, dispatched by filter shape:

    * Mode 1 (flat filters only): same-field values collapse to ``Label in (a, b)``
      when ``group_by_field=True``; different fields are AND-joined alphabetically
      by display label for stable output.
    * Mode 2 (any filter has a ``next_filter`` chain): chains are grouped by
      ``(root_field, root_value)``; siblings sharing the same chain shape collapse
      their leaves into ``in (...)``; root groups are OR-joined.
    """
    if criteria is None or not criteria.has_filters():
        return "(no filters)"

    if any(root.next_filter is not None for root in criteria.filters):
        return _format_mode_2_summary(criteria)
    return _format_mode_1_summary(criteria)


def _format_mode_1_summary(criteria: ScoreDefinitionCriteria) -> str:
    simple_by_field: dict[str, list[str]] = defaultdict(list)
    for root in criteria.filters:
        simple_by_field[root.field].append(root.value)

    rendered: list[tuple[str, str]] = []
    for field, values in simple_by_field.items():
        label = _column_label(field)
        if len(values) == 1:
            rendered.append((label, f"{label} = {values[0]}"))
        elif criteria.group_by_field:
            rendered.append((label, f"{label} in ({', '.join(values)})"))
        else:
            joiner = f" {criteria.operand} "
            rendered.append((label, joiner.join(f"{label} = {v}" for v in values)))

    rendered.sort(key=lambda p: p[0])
    return " AND ".join(part for _, part in rendered)


def _format_mode_2_summary(criteria: ScoreDefinitionCriteria) -> str:
    """Render mode-2 (chained) filters with OR semantics and leaf collapse."""
    grouped: dict[tuple[str, str], list[ScoreDefinitionFilter]] = defaultdict(list)
    for root in criteria.filters:
        grouped[(root.field, root.value)].append(root)

    branches: list[str] = []
    for (root_field, root_value), siblings in grouped.items():
        root_part = f"{_column_label(root_field)} = {root_value}"
        chain_paths: list[list[tuple[str, str]]] = []
        for root in siblings:
            path: list[tuple[str, str]] = []
            current = root.next_filter
            while current is not None:
                path.append((current.field, current.value))
                current = current.next_filter
            chain_paths.append(path)

        non_empty_paths = [p for p in chain_paths if p]
        has_empty = any(not p for p in chain_paths)

        if not non_empty_paths:
            branches.append(root_part)
            continue

        same_shape = len({tuple(field for field, _ in p) for p in non_empty_paths}) == 1
        if same_shape and not has_empty:
            leaf_fields = [field for field, _ in non_empty_paths[0]]
            leaf_parts: list[str] = []
            for i, field in enumerate(leaf_fields):
                values = [p[i][1] for p in non_empty_paths]
                label = _column_label(field)
                if len(set(values)) == 1:
                    leaf_parts.append(f"{label} = {values[0]}")
                else:
                    leaf_parts.append(f"{label} in ({', '.join(values)})")
            branches.append(f"{root_part} AND {' AND '.join(leaf_parts)}")
        else:
            sub_branches: list[str] = []
            for path in chain_paths:
                if not path:
                    sub_branches.append(root_part)
                else:
                    leaves = [f"{_column_label(field)} = {value}" for field, value in path]
                    sub_branches.append(f"({root_part} AND {' AND '.join(leaves)})")
            branches.append(" OR ".join(sub_branches))

    if len(branches) == 1:
        return branches[0]
    return " OR ".join(f"({b})" if " AND " in b else b for b in branches)


def _column_label(column: str) -> str:
    return _COLUMN_TO_LABEL.get(column, column)
