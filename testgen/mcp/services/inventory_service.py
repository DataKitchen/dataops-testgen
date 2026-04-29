from uuid import UUID

from sqlalchemy import and_, select

from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.project import Project
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
    for code in view_codes_set:
        summaries, _ = TableGroup.select_summary(code)
        for summary in summaries:
            profiling_by_tg[summary.id] = summary

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

                if compact_groups or not can_view:
                    line = (
                        f"- **{group['name']}**: id: `{group_id}`, schema: `{group['schema']}`, "
                        f"test suites: {len(group['suites'])}"
                    )
                    if summary:
                        line += f", {_profiling_summary_fragment(summary)}"
                    lines.append(line)
                    continue

                lines.append(
                    f"#### Table Group: {group['name']} (id: `{group_id}`, schema: `{group['schema']}`)\n"
                )

                if summary:
                    lines.append(f"_{_profiling_summary_fragment(summary)}_\n")

                if not group["suites"]:
                    lines.append("_No test suites._\n")
                    continue

                for suite in group["suites"]:
                    lines.append(f"- **{suite['name']}** (id: `{suite['id']}`)")
                lines.append("")

            lines.append("")

    lines.append(
        "---\n"
        "Use `list_tables(table_group_id='...')` to see tables in a group.\n"
        "Use `list_test_suites(project_code='...')` for suite details and latest run stats.\n"
        "Use `list_profiling_summaries(table_group_id='...')` for the quality score rollup and anomaly counts."
    )

    return "\n".join(lines)


def _profiling_summary_fragment(summary: TableGroupSummary) -> str:
    """Compact one-liner of profiling metadata for a table group."""
    if not summary.latest_profile_id:
        return "not profiled yet"

    anomaly_total = (
        (summary.latest_anomalies_definite_ct or 0)
        + (summary.latest_anomalies_likely_ct or 0)
        + (summary.latest_anomalies_possible_ct or 0)
    )
    combined = friendly_score(score(summary.dq_score_profiling, summary.dq_score_testing))
    profiled_at = (
        summary.latest_profile_start.strftime("%Y-%m-%d")
        if summary.latest_profile_start else "—"
    )
    return (
        f"Score {combined}, anomalies {anomaly_total}, "
        f"last profiled {profiled_at}, "
        f"profiling run `{summary.latest_profile_job_execution_id}`"
    )
