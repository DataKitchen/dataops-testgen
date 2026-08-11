"""MCP tools that operate across multiple profiling runs of a table group.

- ``compare_profiling_runs`` — diff two runs (metric changes for shared columns + hygiene churn).
- ``get_profiling_trends`` — caller-named metric time-series across recent runs.
- ``get_schema_history`` — per-run structural changes (tables/columns added/dropped/re-typed)
  with table record-count deltas.

Structural enumeration intentionally lives only in ``get_schema_history``; the comparison tool
renders a one-line pointer to it rather than duplicating the per-table churn.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, NamedTuple
from uuid import UUID

from pydantic import Field
from sqlalchemy import func

from testgen.common.enums import Disposition, JobStatus
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.data_column import ProfileMetric
from testgen.common.models.hygiene_issue import HygieneIssue, HygieneIssueType
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import ProfilingRun, ProfilingRunSummary
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    parse_profile_metrics,
    resolve_profiling_run,
    resolve_table_group,
    validate_limit,
)
from testgen.mcp.tools.markdown import MdDoc
from testgen.utils import friendly_score

_DOC_GROUP = DocGroup.BROWSE_PROFILING


# ---------------------------------------------------------------------------
# General-type vocabulary
# ---------------------------------------------------------------------------

# Single-letter general_type codes (stored on ProfileResult.general_type and
# DataColumnChars.general_type). Mirrors GENERAL_TYPE_TO_CODE values but locally
# named for readability inside this module's scope/type-restriction tables.
_TYPE_ALPHA = "A"
_TYPE_NUMERIC = "N"
_TYPE_DATE = "D"
_TYPE_BOOLEAN = "B"

_TYPE_LABELS: dict[str, str] = {
    _TYPE_ALPHA: "Alpha",
    _TYPE_NUMERIC: "Numeric",
    _TYPE_DATE: "Date",
    _TYPE_BOOLEAN: "Boolean",
    "T": "Time",
    "X": "Other",
}


# ---------------------------------------------------------------------------
# Metric scope + extraction
# ---------------------------------------------------------------------------

_SCOPE_TABLE_GROUP = "table_group"
_SCOPE_TABLE = "table"
_SCOPE_COLUMN = "column"

_METRIC_SCOPE: dict[ProfileMetric, str] = {
    ProfileMetric.NULL_RATIO: _SCOPE_COLUMN,
    ProfileMetric.DISTINCT_RATIO: _SCOPE_COLUMN,
    ProfileMetric.FILLED_RATIO: _SCOPE_COLUMN,
    ProfileMetric.MIN_LENGTH: _SCOPE_COLUMN,
    ProfileMetric.MAX_LENGTH: _SCOPE_COLUMN,
    ProfileMetric.AVG_LENGTH: _SCOPE_COLUMN,
    ProfileMetric.MIN: _SCOPE_COLUMN,
    ProfileMetric.MAX: _SCOPE_COLUMN,
    ProfileMetric.AVG: _SCOPE_COLUMN,
    ProfileMetric.STDEV: _SCOPE_COLUMN,
    ProfileMetric.MIN_DATE: _SCOPE_COLUMN,
    ProfileMetric.MAX_DATE: _SCOPE_COLUMN,
    ProfileMetric.TRUE_COUNT: _SCOPE_COLUMN,
    ProfileMetric.RECORD_COUNT: _SCOPE_TABLE,
    ProfileMetric.PROFILING_SCORE: _SCOPE_TABLE_GROUP,
    ProfileMetric.HYGIENE_COUNT: _SCOPE_TABLE_GROUP,
}

# Type-specific metrics only return a value when the column's general_type matches.
_METRIC_TYPE: dict[ProfileMetric, str] = {
    ProfileMetric.MIN_LENGTH: _TYPE_ALPHA,
    ProfileMetric.MAX_LENGTH: _TYPE_ALPHA,
    ProfileMetric.AVG_LENGTH: _TYPE_ALPHA,
    ProfileMetric.MIN: _TYPE_NUMERIC,
    ProfileMetric.MAX: _TYPE_NUMERIC,
    ProfileMetric.AVG: _TYPE_NUMERIC,
    ProfileMetric.STDEV: _TYPE_NUMERIC,
    ProfileMetric.MIN_DATE: _TYPE_DATE,
    ProfileMetric.MAX_DATE: _TYPE_DATE,
    ProfileMetric.TRUE_COUNT: _TYPE_BOOLEAN,
}

# Metrics rendered as percentages.
_PERCENT_METRICS = {
    ProfileMetric.NULL_RATIO,
    ProfileMetric.DISTINCT_RATIO,
    ProfileMetric.FILLED_RATIO,
}


def _validate_metric_scope(metrics: list[ProfileMetric], table_name: str | None, column_name: str | None) -> None:
    """Reject when any metric needs a deeper scope than the provided arguments offer."""
    needs_column = [m for m in metrics if _METRIC_SCOPE[m] == _SCOPE_COLUMN]
    needs_table = [m for m in metrics if _METRIC_SCOPE[m] == _SCOPE_TABLE]
    if needs_column and column_name is None:
        names = ", ".join(f"`{m.value}`" for m in needs_column)
        raise MCPUserError(f"Metrics {names} require both `table_name` and `column_name`.")
    if needs_table and table_name is None:
        names = ", ".join(f"`{m.value}`" for m in needs_table)
        raise MCPUserError(f"Metrics {names} require `table_name`.")


def _column_metric_value(metric: ProfileMetric, pr: ProfileResult | None) -> object | None:
    """Extract a column-scope metric value from a ProfileResult row.

    Returns ``None`` if the row is missing or the metric doesn't apply to the
    column's ``general_type`` (e.g. ``Average Length`` on a numeric column).
    """
    if pr is None:
        return None
    required_type = _METRIC_TYPE.get(metric)
    if required_type is not None and pr.general_type != required_type:
        return None
    record_ct = pr.record_ct
    if metric is ProfileMetric.NULL_RATIO:
        return pr.null_value_ct / record_ct if record_ct and pr.null_value_ct is not None else None
    if metric is ProfileMetric.DISTINCT_RATIO:
        return pr.distinct_value_ct / record_ct if record_ct and pr.distinct_value_ct is not None else None
    if metric is ProfileMetric.FILLED_RATIO:
        return pr.filled_value_ct / record_ct if record_ct and pr.filled_value_ct is not None else None
    if metric is ProfileMetric.RECORD_COUNT:
        return pr.record_ct
    if metric is ProfileMetric.MIN_LENGTH:
        return pr.min_length
    if metric is ProfileMetric.MAX_LENGTH:
        return pr.max_length
    if metric is ProfileMetric.AVG_LENGTH:
        return pr.avg_length
    if metric is ProfileMetric.MIN:
        return pr.min_value
    if metric is ProfileMetric.MAX:
        return pr.max_value
    if metric is ProfileMetric.AVG:
        return pr.avg_value
    if metric is ProfileMetric.STDEV:
        return pr.stdev_value
    if metric is ProfileMetric.MIN_DATE:
        return pr.min_date
    if metric is ProfileMetric.MAX_DATE:
        return pr.max_date
    if metric is ProfileMetric.TRUE_COUNT:
        return pr.boolean_true_ct
    return None


def _format_metric_value(metric: ProfileMetric, value: object | None) -> str:
    if value is None:
        return "—"
    if metric is ProfileMetric.PROFILING_SCORE and isinstance(value, int | float):
        return friendly_score(value) or "—"
    if metric in _PERCENT_METRICS and isinstance(value, int | float):
        return f"{float(value) * 100:.1f}%"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, float):
        # 6 significant digits with thousands separators preserves precision for
        # ratios in the 0.x range (e.g. 5.94821) while keeping wide values readable
        # (e.g. 12,345.6).
        return f"{value:,.6g}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _delta_cell(metric: ProfileMetric, baseline: object | None, target: object | None) -> str:
    """Render a baseline → target cell. ``B (=)`` when unchanged after formatting.

    Equality is checked on the formatted strings, not the raw values — two timestamps
    that render as the same date display as ``(=)`` rather than a no-op ``→``.
    """
    baseline_str = _format_metric_value(metric, baseline)
    target_str = _format_metric_value(metric, target)
    if baseline_str == target_str:
        return f"{target_str} (=)"
    return f"{baseline_str} → {target_str}"


# ---------------------------------------------------------------------------
# Run-state guard
# ---------------------------------------------------------------------------


def _require_completed(run: ProfilingRun, label: str) -> None:
    """Raise if the run's job execution isn't completed."""
    je = get_current_session().get(JobExecution, run.id)
    if je.status != JobStatus.COMPLETED:
        status_label = ProfilingRunSummary.STATUS_LABEL.get(je.status, je.status)
        raise MCPUserError(
            f"{label} run is in `{status_label}` state — comparison requires a completed run."
        )


# ---------------------------------------------------------------------------
# Compare profiling runs
# ---------------------------------------------------------------------------


# Per-general-type metric tables. Excludes the type-display column header so the
# table is uniformly wide; cross-flavor type-display drift is surfaced via footnote.
_METRIC_TABLE_BY_TYPE: dict[str, list[ProfileMetric]] = {
    _TYPE_NUMERIC: [
        ProfileMetric.NULL_RATIO,
        ProfileMetric.DISTINCT_RATIO,
        ProfileMetric.MIN,
        ProfileMetric.MAX,
        ProfileMetric.AVG,
        ProfileMetric.STDEV,
        ProfileMetric.RECORD_COUNT,
    ],
    _TYPE_ALPHA: [
        ProfileMetric.NULL_RATIO,
        ProfileMetric.DISTINCT_RATIO,
        ProfileMetric.AVG_LENGTH,
        ProfileMetric.MIN_LENGTH,
        ProfileMetric.MAX_LENGTH,
        ProfileMetric.RECORD_COUNT,
    ],
    _TYPE_DATE: [
        ProfileMetric.NULL_RATIO,
        ProfileMetric.MIN_DATE,
        ProfileMetric.MAX_DATE,
        ProfileMetric.RECORD_COUNT,
    ],
    _TYPE_BOOLEAN: [
        ProfileMetric.NULL_RATIO,
        ProfileMetric.TRUE_COUNT,
        ProfileMetric.RECORD_COUNT,
    ],
}

# Categorical attributes rendered only when they change. Keys are user-facing
# field labels; values are ProfileResult attribute names.
_CATEGORICAL_FIELDS: dict[str, str] = {
    "Type": "column_type",
    "Semantic Type": "functional_data_type",
    "PII": "pii_flag",
    "Suggested Type": "datatype_suggestion",
}


def _pair_results(
    rows: Iterable[ProfileResult], target_run_id: UUID, baseline_run_id: UUID,
) -> dict[tuple[str, str, str], dict[str, ProfileResult]]:
    """Group profile-results by (schema, table, column) and tag each row as target/baseline."""
    by_key: dict[tuple[str, str, str], dict[str, ProfileResult]] = defaultdict(dict)
    for row in rows:
        key = (row.schema_name, row.table_name, row.column_name)
        if row.profile_run_id == target_run_id:
            by_key[key]["target"] = row
        elif row.profile_run_id == baseline_run_id:
            by_key[key]["baseline"] = row
    return by_key


@with_database_session
@mcp_permission("catalog")
def compare_profiling_runs(
    target_job_execution_id: Annotated[
        str,
        Field(description='UUID of the newer profiling run (the "after" snapshot), e.g. from `list_profiling_runs`.'),
    ],
    baseline_job_execution_id: Annotated[
        str | None,
        Field(
            description='Optional UUID of the older profiling run (the "before" snapshot). When omitted, defaults to '
            "the previous completed run on the same table group.",
        ),
    ] = None,
    table_name: Annotated[
        str | None,
        Field(description="Optional — restrict the comparison to one table (case-sensitive)."),
    ] = None,
    column_name: Annotated[
        str | None,
        Field(description="Optional — restrict the comparison to one column (case-sensitive); requires `table_name`."),
    ] = None,
) -> str:
    """Compare two profiling runs on the same table group.
    Reports metric changes for shared columns plus hygiene issue churn.

    When ``baseline_job_execution_id`` is omitted, the baseline defaults to the most recent
    completed profiling run on the same table group submitted before the target run. Both
    runs must be in `Completed` state.

    Reports only on columns present in both runs. When structural drift exists, the output
    notes that fact in one line; the per-table/column structural diff is not enumerated here.
    """
    if column_name is not None and table_name is None:
        raise MCPUserError("`column_name` requires `table_name`.")

    target_run = resolve_profiling_run(target_job_execution_id)
    _require_completed(target_run, "Target")

    if baseline_job_execution_id is None:
        baseline_run = target_run.get_previous()
        if baseline_run is None:
            raise MCPUserError(
                f"Target run `{target_job_execution_id}` has no earlier completed "
                "profiling run on its table group to compare against."
            )
    else:
        baseline_run = resolve_profiling_run(baseline_job_execution_id)
        if baseline_run.table_groups_id != target_run.table_groups_id:
            raise MCPUserError(
                "Both runs must belong to the same table group to be comparable. "
                f"Target is in table group `{target_run.table_groups_id}`, "
                f"baseline is in table group `{baseline_run.table_groups_id}`."
            )
    _require_completed(baseline_run, "Baseline")

    rows = ProfileResult.select_for_runs(
        run_ids=[target_run.id, baseline_run.id],
        table_name=table_name,
        column_name=column_name,
    )
    paired = _pair_results(rows, target_run.id, baseline_run.id)

    has_structural_changes = any(
        "target" not in sides or "baseline" not in sides for sides in paired.values()
    )
    shared = {key: sides for key, sides in paired.items() if "target" in sides and "baseline" in sides}

    hygiene_diff = _diff_hygiene_issues(
        target_run.id, baseline_run.id, table_name=table_name, column_name=column_name,
    )

    return _render_run_comparison(
        target_run=target_run,
        baseline_run=baseline_run,
        shared=shared,
        has_structural_changes=has_structural_changes,
        hygiene_diff=hygiene_diff,
    )


class _HygieneRow(NamedTuple):
    table_name: str
    column_name: str
    issue_type: str


def _diff_hygiene_issues(
    target_run_id: UUID,
    baseline_run_id: UUID,
    table_name: str | None,
    column_name: str | None,
) -> dict[str, list[_HygieneRow]]:
    """Return ``{"added": [...], "resolved": [...]}`` lists of hygiene-issue rows.

    Matches issues across the two runs by (table, column, type_id) — only confirmed
    issues (default disposition) are counted.
    """
    clauses = [
        HygieneIssue.profile_run_id.in_([target_run_id, baseline_run_id]),
        func.coalesce(HygieneIssue.disposition, Disposition.CONFIRMED) == Disposition.CONFIRMED,
    ]
    if table_name is not None:
        clauses.append(HygieneIssue.table_name == table_name)
    if column_name is not None:
        clauses.append(HygieneIssue.column_name == column_name)
    issues = list(HygieneIssue.select_where(*clauses))

    type_ids = {issue.type_id for issue in issues}
    type_names: dict[str, str] = {}
    if type_ids:
        type_names = {
            t.id: t.name for t in HygieneIssueType.select_where(HygieneIssueType.id.in_(type_ids))
        }

    target_keys: set[tuple[str, str, str]] = set()
    baseline_keys: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (issue.table_name, issue.column_name, issue.type_id)
        if issue.profile_run_id == target_run_id:
            target_keys.add(key)
        else:
            baseline_keys.add(key)

    def _rows(keys: Iterable[tuple[str, str, str]]) -> list[_HygieneRow]:
        return sorted(
            (_HygieneRow(t, c, type_names.get(tid, tid)) for t, c, tid in keys),
            key=lambda r: (r.table_name, r.column_name, r.issue_type),
        )

    return {
        "added": _rows(target_keys - baseline_keys),
        "resolved": _rows(baseline_keys - target_keys),
    }


def _categorical_change(label: str, baseline: ProfileResult, target: ProfileResult) -> tuple[str, str] | None:
    """Return ``(label, "B → T")`` when a categorical field changed, else ``None``."""
    attr = _CATEGORICAL_FIELDS[label]
    baseline_value = getattr(baseline, attr)
    target_value = getattr(target, attr)
    if baseline_value == target_value:
        return None
    baseline_display = baseline_value if baseline_value is not None else "—"
    target_display = target_value if target_value is not None else "—"
    return label, f"{baseline_display} → {target_display}"


def _build_metric_rows_for_type(
    general_type: str,
    shared: dict[tuple[str, str, str], dict[str, ProfileResult]],
) -> tuple[list[str], list[list[str]]]:
    """Build (headers, rows) for the metric-change table for one general_type bucket."""
    metrics = _METRIC_TABLE_BY_TYPE[general_type]
    headers = ["Table", "Column", *(m.value for m in metrics)]
    rows: list[list[str]] = []
    for (_, table, column), sides in sorted(shared.items()):
        baseline = sides["baseline"]
        target = sides["target"]
        # Bucket by target's type. Columns that switched type between runs render here
        # under the new type; the old/new type is also surfaced as a categorical change.
        if target.general_type != general_type:
            continue
        # Only render columns that changed in at least one metric in this bucket.
        deltas: list[str] = []
        any_changed = False
        for metric in metrics:
            target_value = _column_metric_value(metric, target)
            baseline_value = _column_metric_value(metric, baseline)
            if target_value != baseline_value:
                any_changed = True
            deltas.append(_delta_cell(metric, baseline_value, target_value))
        if any_changed:
            rows.append([table, column, *deltas])
    return headers, rows


def _categorical_lines(
    shared: dict[tuple[str, str, str], dict[str, ProfileResult]],
) -> list[str]:
    """Return one bullet per shared column that has at least one categorical change."""
    lines: list[str] = []
    for (_, table, column), sides in sorted(shared.items()):
        baseline = sides["baseline"]
        target = sides["target"]
        changes: list[str] = []
        for label in _CATEGORICAL_FIELDS:
            change = _categorical_change(label, baseline, target)
            if change is not None:
                changes.append(f"{change[0]}: {change[1]}")
        if changes:
            lines.append(f"`{table}.{column}` — {', '.join(changes)}")
    return lines


def _render_run_comparison(
    target_run: ProfilingRun,
    baseline_run: ProfilingRun,
    shared: dict[tuple[str, str, str], dict[str, ProfileResult]],
    has_structural_changes: bool,
    hygiene_diff: dict[str, list[_HygieneRow]],
) -> str:
    doc = MdDoc()
    doc.heading(1, "Profiling Run Comparison")
    doc.table(
        ["", "Target", "Baseline"],
        [
            ["Profiling Run",
             MdDoc.code(str(target_run.id)),
             MdDoc.code(str(baseline_run.id))],
            ["Started", target_run.profiling_starttime, baseline_run.profiling_starttime],
        ],
    )

    if has_structural_changes:
        doc.text(
            "_Structural changes also occurred between these runs — "
            "call `get_schema_history(table_group_id)` for the per-table/column diff._"
        )

    # Metric tables, one per general_type bucket
    rendered_any_metric_table = False
    for general_type in (_TYPE_NUMERIC, _TYPE_ALPHA, _TYPE_DATE, _TYPE_BOOLEAN):
        headers, rows = _build_metric_rows_for_type(general_type, shared)
        if rows:
            rendered_any_metric_table = True
            doc.heading(2, f"{_TYPE_LABELS[general_type]} columns")
            doc.table(headers, rows, code=[0, 1])

    categorical_lines = _categorical_lines(shared)
    if categorical_lines:
        doc.heading(2, "Categorical changes")
        doc.bullets(categorical_lines)

    added = hygiene_diff["added"]
    resolved = hygiene_diff["resolved"]
    if added or resolved:
        doc.heading(2, "Hygiene issues")
        if resolved:
            doc.heading(3, f"Resolved ({len(resolved)})")
            doc.table(
                ["Table", "Column", "Issue type"],
                [[r.table_name, r.column_name, r.issue_type] for r in resolved],
                code=[0, 1],
            )
        if added:
            doc.heading(3, f"Added ({len(added)})")
            doc.table(
                ["Table", "Column", "Issue type"],
                [[r.table_name, r.column_name, r.issue_type] for r in added],
                code=[0, 1],
            )

    if not (rendered_any_metric_table or categorical_lines or added or resolved or has_structural_changes):
        doc.text("_No changes between target and baseline._")

    return doc.render()


# ---------------------------------------------------------------------------
# Profiling trends
# ---------------------------------------------------------------------------


@with_database_session
@mcp_permission("catalog")
def get_profiling_trends(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    metrics: Annotated[
        list[str],
        Field(
            description="One or more metric names. Accepted values: `Null Ratio`, `Distinct Ratio`, `Filled Ratio`, "
            "`Row Count`, `Profiling Score`, `Hygiene Issues`, `Minimum Length`, `Maximum Length`, `Average Length`, "
            "`Minimum Value`, `Maximum Value`, `Average Value`, `Standard Deviation`, `Minimum Date`, `Maximum Date`, "
            "`True Count`.",
        ),
    ],
    table_name: Annotated[str | None, Field(description="Optional — restrict to one table (case-sensitive).")] = None,
    column_name: Annotated[
        str | None,
        Field(description="Optional — restrict to one column (case-sensitive); requires `table_name`."),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Number of most-recent completed runs to include (default 10, max 50)."),
    ] = 10,
) -> str:
    """Show a time series of caller-named profiling metrics.
    Covers recent completed runs of a table group.

    Metric scope rules:
    - Column-level metrics (e.g. `Null Ratio`, `Average Length`, `Minimum Value`) require both
      `table_name` and `column_name`.
    - `Row Count` is table-level and requires `table_name`.
    - `Profiling Score` and `Hygiene Issues` are table-group-level and accept any scope.
    - Type-specific metrics return `—` for runs where the column's general type
      didn't match (e.g. `Minimum Value` on a column that was Alpha in an earlier run).
    """
    validate_limit(limit, 50)
    if column_name is not None and table_name is None:
        raise MCPUserError("`column_name` requires `table_name`.")

    tg = resolve_table_group(table_group_id)
    metric_enums = parse_profile_metrics(metrics)
    _validate_metric_scope(metric_enums, table_name, column_name)

    runs = ProfilingRun.list_recent_complete(tg.id, limit=limit)
    if not runs:
        return f"No completed profiling runs found for table group `{table_group_id}`."

    run_ids = [r.id for r in runs]
    needs_profile_rows = any(_METRIC_SCOPE[m] in (_SCOPE_COLUMN, _SCOPE_TABLE) for m in metric_enums)
    profile_by_run: dict[UUID, ProfileResult] = {}
    if needs_profile_rows:
        rows = ProfileResult.select_for_runs(
            run_ids=run_ids, table_name=table_name, column_name=column_name,
        )
        if column_name is not None:
            profile_by_run = {row.profile_run_id: row for row in rows}
        else:
            # Table-only scope: there may be many ProfileResult rows per (run, table).
            # All carry the same record_ct (table-level); take any.
            for row in rows:
                profile_by_run.setdefault(row.profile_run_id, row)

    hygiene_counts: dict[UUID, int] = {}
    if ProfileMetric.HYGIENE_COUNT in metric_enums:
        hygiene_counts = ProfilingRun.count_confirmed_hygiene_issues(run_ids)

    # Bound the entity's presence in the window. `first_seen_run` is the oldest run
    # with a profile row; `last_seen_run` is the newest. When either differs from the
    # window extreme on its side, a one-line note explains the leading/trailing `—`
    # cells in the rendered trend table.
    first_seen_run: ProfilingRun | None = None
    last_seen_run: ProfilingRun | None = None
    if needs_profile_rows:
        for run in reversed(runs):
            if run.id in profile_by_run:
                first_seen_run = run
                break
        for run in runs:
            if run.id in profile_by_run:
                last_seen_run = run
                break

    return _render_trends(
        tg_name=tg.table_groups_name,
        runs=runs,
        metrics=metric_enums,
        profile_by_run=profile_by_run,
        hygiene_counts=hygiene_counts,
        table_name=table_name,
        column_name=column_name,
        first_seen_run=first_seen_run,
        last_seen_run=last_seen_run,
        needs_profile_rows=needs_profile_rows,
    )


def _entity_label(table_name: str | None, column_name: str | None) -> str:
    if column_name is not None:
        return f"`{table_name}.{column_name}`"
    if table_name is not None:
        return f"`{table_name}`"
    return ""


def _trend_cell(
    metric: ProfileMetric,
    run: ProfilingRun,
    profile_by_run: dict[UUID, ProfileResult],
    hygiene_counts: dict[UUID, int],
) -> str:
    if metric is ProfileMetric.PROFILING_SCORE:
        return _format_metric_value(metric, run.dq_score_profiling)
    if metric is ProfileMetric.HYGIENE_COUNT:
        return _format_metric_value(metric, hygiene_counts.get(run.id, 0))
    pr = profile_by_run.get(run.id)
    return _format_metric_value(metric, _column_metric_value(metric, pr))


def _render_trends(
    tg_name: str,
    runs: list[ProfilingRun],
    metrics: list[ProfileMetric],
    profile_by_run: dict[UUID, ProfileResult],
    hygiene_counts: dict[UUID, int],
    table_name: str | None,
    column_name: str | None,
    first_seen_run: ProfilingRun | None,
    last_seen_run: ProfilingRun | None,
    needs_profile_rows: bool,
) -> str:
    doc = MdDoc()
    entity = _entity_label(table_name, column_name)
    title = f"Profiling trends for {entity} in `{tg_name}`" if entity else f"Profiling trends for `{tg_name}`"
    doc.heading(1, title)
    doc.field("Runs included", len(runs))
    doc.field("Oldest run", runs[-1].profiling_starttime)
    doc.field("Newest run", runs[0].profiling_starttime)

    if needs_profile_rows and first_seen_run is None:
        doc.text(
            f"_{entity} not present in any of the last {len(runs)} runs — nothing to trend._"
        )
        return doc.render()

    if (
        needs_profile_rows
        and first_seen_run is not None
        and first_seen_run.id != runs[-1].id
    ):
        doc.text(
            f"_{entity} first appears in the run started "
            f"{_format_run_label(first_seen_run)}._"
        )
    if (
        needs_profile_rows
        and last_seen_run is not None
        and last_seen_run.id != runs[0].id
    ):
        doc.text(
            f"_{entity} last appears in the run started "
            f"{_format_run_label(last_seen_run)}._"
        )

    # Newest-first columns
    headers = ["Metric", *(_format_run_label(run) for run in runs)]
    rows: list[list[str]] = []
    for metric in metrics:
        row = [metric.value]
        for run in runs:
            row.append(_trend_cell(metric, run, profile_by_run, hygiene_counts))
        rows.append(row)
    doc.table(headers, rows)

    return doc.render()


# ---------------------------------------------------------------------------
# Schema history
# ---------------------------------------------------------------------------


class _TableSnapshot(NamedTuple):
    columns: dict[str, "_ColumnSnapshot"]
    record_ct: int | None


class _ColumnSnapshot(NamedTuple):
    column_type: str | None
    general_type: str | None
    db_data_type: str | None


def _build_run_snapshots(rows: Iterable[ProfileResult]) -> dict[UUID, dict[tuple[str, str], _TableSnapshot]]:
    """Reduce per-(run, table) profile rows to a column-snapshot map."""
    accumulator: dict[UUID, dict[tuple[str, str], dict[str, _ColumnSnapshot]]] = defaultdict(lambda: defaultdict(dict))
    record_ct: dict[UUID, dict[tuple[str, str], int | None]] = defaultdict(dict)
    for row in rows:
        run_id = row.profile_run_id
        table_key = (row.schema_name, row.table_name)
        accumulator[run_id][table_key][row.column_name] = _ColumnSnapshot(
            column_type=row.column_type,
            general_type=row.general_type,
            db_data_type=row.db_data_type,
        )
        # All rows in a (run, table) carry the same record_ct; first one wins.
        record_ct[run_id].setdefault(table_key, row.record_ct)

    out: dict[UUID, dict[tuple[str, str], _TableSnapshot]] = {}
    for run_id, table_columns in accumulator.items():
        out[run_id] = {
            tk: _TableSnapshot(columns=cols, record_ct=record_ct[run_id].get(tk))
            for tk, cols in table_columns.items()
        }
    return out


@with_database_session
@mcp_permission("catalog")
def get_schema_history(
    table_group_id: Annotated[str, Field(description="UUID of the table group, e.g. from `get_data_inventory`.")],
    limit: Annotated[
        int,
        Field(
            description="Number of recent runs to render deltas for (default 10, max 20). One additional anchor run is "
            "pulled when available so the oldest in-window run has a baseline to diff against.",
        ),
    ] = 10,
) -> str:
    """Show a per-run timeline of structural changes across recent profiling runs.
    Reports tables and columns added or dropped, type changes, and record-count
    deltas per table.
    """
    validate_limit(limit, 20)
    tg = resolve_table_group(table_group_id)

    runs = ProfilingRun.list_recent_complete(tg.id, limit=limit + 1)
    if len(runs) < 2:
        if not runs:
            return f"No completed profiling runs found for table group `{tg.table_groups_name}`."
        return (
            f"Only one completed profiling run exists for table group `{tg.table_groups_name}` — "
            "at least two are needed to render a history."
        )

    run_ids = [r.id for r in runs]
    rows = ProfileResult.select_for_runs(run_ids=run_ids)
    snapshots = _build_run_snapshots(rows)

    return _render_schema_history(tg.table_groups_name, runs, snapshots)


def _render_schema_history(
    tg_name: str,
    runs: list[ProfilingRun],
    snapshots: dict[UUID, dict[tuple[str, str], _TableSnapshot]],
) -> str:
    doc = MdDoc()
    doc.heading(1, f"Schema history for `{tg_name}`")
    doc.field("Runs analyzed", len(runs) - 1)
    doc.field("Window", f"{_format_run_label(runs[-1])} → {_format_run_label(runs[0])}")

    # Iterate newest → oldest, pairing each run with its predecessor.
    for index in range(len(runs) - 1):
        target = runs[index]
        baseline = runs[index + 1]
        section_lines = _format_schema_delta(
            target_snap=snapshots.get(target.id, {}),
            baseline_snap=snapshots.get(baseline.id, {}),
        )
        doc.heading(2, f"Run started {_format_run_label(target)}")
        doc.field("Profiling Run", target.id, code=True)
        if section_lines:
            doc.bullets(section_lines)
        else:
            doc.text("_No structural change since previous run._")

    return doc.render()


def _format_run_label(run: ProfilingRun) -> str:
    """Format a run's start time as ``YYYY-MM-DD HH:MM`` — short enough for column
    headers, precise enough to disambiguate same-day runs."""
    return run.profiling_starttime.strftime("%Y-%m-%d %H:%M")


def _format_table_key(key: tuple[str, str]) -> str:
    schema, table = key
    return f"`{schema}.{table}`" if schema else f"`{table}`"


def _format_schema_delta(
    target_snap: dict[tuple[str, str], _TableSnapshot],
    baseline_snap: dict[tuple[str, str], _TableSnapshot],
) -> list[str]:
    lines: list[str] = []
    target_tables = set(target_snap)
    baseline_tables = set(baseline_snap)

    added_tables = sorted(target_tables - baseline_tables)
    for key in added_tables:
        col_ct = len(target_snap[key].columns)
        lines.append(f"Table added: {_format_table_key(key)} ({col_ct} columns)")

    dropped_tables = sorted(baseline_tables - target_tables)
    for key in dropped_tables:
        col_ct = len(baseline_snap[key].columns)
        lines.append(f"Table dropped: {_format_table_key(key)} ({col_ct} columns)")

    for key in sorted(target_tables & baseline_tables):
        target_table = target_snap[key]
        baseline_table = baseline_snap[key]
        column_changes = _format_column_delta(target_table.columns, baseline_table.columns)
        record_delta = _format_record_delta(target_table.record_ct, baseline_table.record_ct)
        for change in column_changes:
            lines.append(f"{_format_table_key(key)}: {change}")
        if record_delta is not None:
            lines.append(f"{_format_table_key(key)}: Record count {record_delta}")
    return lines


def _format_column_delta(
    target_cols: dict[str, _ColumnSnapshot],
    baseline_cols: dict[str, _ColumnSnapshot],
) -> list[str]:
    out: list[str] = []
    target_names = set(target_cols)
    baseline_names = set(baseline_cols)
    for name in sorted(target_names - baseline_names):
        snap = target_cols[name]
        type_label = snap.column_type or snap.db_data_type
        out.append(f"column `{name}` added ({type_label})" if type_label else f"column `{name}` added")
    for name in sorted(baseline_names - target_names):
        snap = baseline_cols[name]
        type_label = snap.column_type or snap.db_data_type
        out.append(f"column `{name}` dropped (was {type_label})" if type_label else f"column `{name}` dropped")
    for name in sorted(target_names & baseline_names):
        target_col = target_cols[name]
        baseline_col = baseline_cols[name]
        if target_col.column_type != baseline_col.column_type and target_col.column_type and baseline_col.column_type:
            out.append(
                f"column `{name}` retyped: {baseline_col.column_type} → {target_col.column_type}"
            )
    return out


def _format_record_delta(target_ct: int | None, baseline_ct: int | None) -> str | None:
    if target_ct is None or baseline_ct is None:
        return None
    if target_ct == baseline_ct:
        return None
    return f"{baseline_ct:,} → {target_ct:,}"
