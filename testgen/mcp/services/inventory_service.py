from sqlalchemy import and_, select

from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite


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
                if compact_groups or not can_view:
                    lines.append(
                        f"- **{group['name']}**: id: `{group_id}`, schema: `{group['schema']}`, "
                        f"test suites: {len(group['suites'])}"
                    )
                    continue

                lines.append(
                    f"#### Table Group: {group['name']} (id: `{group_id}`, schema: `{group['schema']}`)\n"
                )

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
        "Use `list_test_suites(project_code='...')` for suite details and latest run stats."
    )

    return "\n".join(lines)
