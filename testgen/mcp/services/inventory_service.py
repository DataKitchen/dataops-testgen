from uuid import UUID

from sqlalchemy import and_, select

from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.project import Project
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup, TableGroupSummary
from testgen.common.models.test_suite import TestSuite
from testgen.utils import friendly_score, score


def get_inventory(
    project_codes: list[str],
    view_project_codes: list[str],
) -> str:
    """Build a markdown inventory of all projects, connections, table groups, and test suites.

    Args:
        project_codes: Projects the user can see (based on decorator permission).
        view_project_codes: Projects where the user has 'view' permission.
            Connection names and test suites are only shown for these projects.
            Table groups are always shown so catalog users can browse tables.
    """
    session = get_current_session()

    query = (
        select(
            Project.project_code,
            Project.project_name,
            Connection.connection_id,
            Connection.connection_name,
            TableGroup.id.label("table_group_id"),
            TableGroup.table_groups_name,
            TableGroup.table_group_schema,
            TestSuite.id.label("test_suite_id"),
            TestSuite.test_suite,
        )
        .outerjoin(Connection, Connection.project_code == Project.project_code)
        .outerjoin(TableGroup, TableGroup.connection_id == Connection.connection_id)
        .outerjoin(
            TestSuite,
            and_(
                TestSuite.table_groups_id == TableGroup.id,
                TestSuite.is_monitor.isnot(True),
            ),
        )
    )

    query = query.where(Project.project_code.in_(project_codes))

    query = query.order_by(
        Project.project_name, Connection.connection_name, TableGroup.table_groups_name, TestSuite.test_suite,
    )

    rows = session.execute(query).all()

    # Build nested structure
    projects: dict[str, dict] = {}
    total_groups = 0

    for row in rows:
        proj = projects.setdefault(row.project_code, {
            "name": row.project_name,
            "connections": {},
        })
        if row.connection_id is None:
            continue

        conn = proj["connections"].setdefault(row.connection_id, {
            "name": row.connection_name,
            "groups": {},
        })
        if row.table_group_id is None:
            continue

        group = conn["groups"].setdefault(row.table_group_id, {
            "name": row.table_groups_name,
            "schema": row.table_group_schema,
            "suites": [],
        })
        if row.test_suite_id is not None:
            group["suites"].append({
                "id": str(row.test_suite_id),
                "name": row.test_suite,
            })

    total_groups = sum(
        len(conn["groups"])
        for proj in projects.values()
        for conn in proj["connections"].values()
    )
    compact_groups = total_groups > 50

    view_codes_set = set(view_project_codes)

    profiling_by_tg: dict[UUID, TableGroupSummary] = {}
    scorecards_by_project: dict[str, tuple[dict[str, list[tuple[str, str]]], list[tuple[str, str]]]] = {}
    for code in view_codes_set:
        summaries, _ = TableGroup.select_summary(code)
        for summary in summaries:
            profiling_by_tg[summary.id] = summary
        scorecards_by_project[code] = _scorecards_by_table_group(code)

    # Format as Markdown
    lines = ["# Data Inventory\n"]

    for project_code, proj in projects.items():
        can_view = project_code in view_codes_set
        lines.append(f"## Project: {proj['name']} (`{project_code}`)\n")

        if not proj["connections"]:
            if can_view:
                lines.append("_No connections configured._\n")
            else:
                lines.append("_No table groups._\n")
            continue

        for _conn_id, conn in proj["connections"].items():
            if can_view:
                lines.append(f"### Connection: {conn['name']}\n")

            if not conn["groups"]:
                if can_view:
                    lines.append("_No table groups._\n")
                continue

            for group_id, group in conn["groups"].items():
                summary = profiling_by_tg.get(group_id) if can_view else None
                tg_scorecards: list[tuple[str, str]] = []
                if can_view:
                    by_tg, _ = scorecards_by_project[project_code]
                    tg_scorecards = by_tg.get(group["name"], [])

                if compact_groups or not can_view:
                    line = (
                        f"- **{group['name']}**: id: `{group_id}`, schema: `{group['schema']}`, "
                        f"test suites: {len(group['suites'])}"
                    )
                    if summary:
                        line += f", {_profiling_summary_fragment(summary)}"
                    if tg_scorecards:
                        line += f", scorecards: {len(tg_scorecards)}"
                    lines.append(line)
                    continue

                lines.append(
                    f"#### Table Group: {group['name']} (id: `{group_id}`, schema: `{group['schema']}`)\n"
                )

                if summary:
                    lines.append(f"_{_profiling_summary_fragment(summary)}_\n")

                if tg_scorecards:
                    lines.append("**Scorecards:**")
                    for sid, name in tg_scorecards:
                        lines.append(f"- **{name}** (id: `{sid}`)")
                    lines.append("")

                if not group["suites"]:
                    lines.append("_No test suites._\n")
                    continue

                lines.append("**Test Suites:**")
                for suite in group["suites"]:
                    lines.append(f"- **{suite['name']}** (id: `{suite['id']}`)")
                lines.append("")

            lines.append("")

        if can_view:
            _, multi = scorecards_by_project.get(project_code, ({}, []))
            if multi:
                lines.append("### Scorecards spanning multiple table groups\n")
                for sid, name in multi:
                    lines.append(f"- **{name}** (id: `{sid}`)")
                lines.append("")

    lines.append(
        "---\n"
        "Use `list_tables(table_group_id='...')` to see tables in a group.\n"
        "Use `list_test_suites(project_code='...')` for suite details and latest run stats.\n"
        "Use `list_profiling_summaries(table_group_id='...')` for the quality score rollup and hygiene issue counts.\n"
        "Use `get_scorecard(scorecard_id='...')` for the score breakdown and category detail."
    )

    return "\n".join(lines)


def _scorecards_by_table_group(
    project_code: str,
) -> tuple[dict[str, list[tuple[str, str]]], list[tuple[str, str]]]:
    """Index scorecards in a project by the table groups they target by name.

    Returns (by_tg_name, multi_or_none):
      - by_tg_name[tg_name] = list of (scorecard_id_str, scorecard_name) for
        scorecards that declare a `table_groups_name = tg_name` filter.
      - multi_or_none lists scorecards whose name-filter count is not exactly 1
        (zero filters → project-wide; multiple → spans TGs by name). Such
        scorecards appear under every named TG AND in this list.
    """
    by_tg: dict[str, list[tuple[str, str]]] = {}
    multi_or_none: list[tuple[str, str]] = []
    for sc_id, sc_name, tg_names in ScoreDefinition.list_with_table_group_targets(project_code):
        entry = (str(sc_id), sc_name)
        for tg_name in tg_names:
            by_tg.setdefault(tg_name, []).append(entry)
        if len(tg_names) != 1:
            multi_or_none.append(entry)
    return by_tg, multi_or_none


def _profiling_summary_fragment(summary: TableGroupSummary) -> str:
    """Compact one-liner of profiling metadata for a table group."""
    if not summary.latest_profile_id:
        return "not profiled yet"

    hygiene_issue_total = (
        (summary.latest_hygiene_issues_definite_ct or 0)
        + (summary.latest_hygiene_issues_likely_ct or 0)
        + (summary.latest_hygiene_issues_possible_ct or 0)
    )
    combined = friendly_score(score(summary.dq_score_profiling, summary.dq_score_testing))
    profiled_at = (
        summary.latest_profile_start.strftime("%Y-%m-%d")
        if summary.latest_profile_start else "—"
    )
    return (
        f"Score {combined}, hygiene issues {hygiene_issue_total}, "
        f"last profiled {profiled_at}, "
        f"profiling run `{summary.latest_profile_job_execution_id}`"
    )
