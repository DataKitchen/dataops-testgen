from sqlalchemy import and_, select

from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_table import DataTable
from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite


def get_inventory() -> str:
    """Build a markdown inventory of all projects, connections, table groups, and test suites."""
    session = get_current_session()

    query = (
        select(
            Project.project_code,
            Project.project_name,
            Connection.connection_id,
            Connection.connection_name,
            Connection.sql_flavor_code,
            TableGroup.id.label("table_group_id"),
            TableGroup.table_groups_name,
            TableGroup.table_group_schema,
            TestSuite.id.label("test_suite_id"),
            TestSuite.test_suite,
            TestRun.id.label("last_run_id"),
            TestRun.test_starttime,
            TestRun.status.label("last_run_status"),
            TestRun.test_ct,
            TestRun.passed_ct,
            TestRun.failed_ct,
            TestRun.warning_ct,
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
        .outerjoin(TestRun, TestRun.id == TestSuite.last_complete_test_run_id)
        .order_by(Project.project_name, Connection.connection_name, TableGroup.table_groups_name, TestSuite.test_suite)
    )

    rows = session.execute(query).all()

    # Collect table stats per project
    project_codes = {row.project_code for row in rows if row.project_code}
    stats_by_group = {}
    for project_code in project_codes:
        for stat in TableGroup.select_stats(project_code):
            stats_by_group[stat.id] = stat

    # Collect table names per group (first 100)
    group_ids = {row.table_group_id for row in rows if row.table_group_id}
    tables_by_group: dict = {}
    for gid in group_ids:
        table_names = DataTable.select_table_names(gid, limit=100)
        if table_names:
            tables_by_group[gid] = table_names

    # Build nested structure
    projects: dict[str, dict] = {}
    total_suites = 0

    for row in rows:
        proj = projects.setdefault(row.project_code, {
            "name": row.project_name,
            "connections": {},
        })
        if row.connection_id is None:
            continue

        conn = proj["connections"].setdefault(row.connection_id, {
            "name": row.connection_name,
            "flavor": row.sql_flavor_code,
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
            total_suites += 1
            group["suites"].append({
                "id": str(row.test_suite_id),
                "name": row.test_suite,
                "last_run_id": str(row.last_run_id) if row.last_run_id else None,
                "last_run_time": str(row.test_starttime) if row.test_starttime else None,
                "last_run_status": row.last_run_status,
                "test_ct": row.test_ct,
                "passed_ct": row.passed_ct,
                "failed_ct": row.failed_ct,
                "warning_ct": row.warning_ct,
            })

    # Compact mode for large inventories
    compact_suites = total_suites > 20
    total_groups = sum(
        len(conn["groups"])
        for proj in projects.values()
        for conn in proj["connections"].values()
    )
    compact_groups = total_groups > 50

    # Format as Markdown
    lines = ["# Data Inventory\n"]

    for project_code, proj in projects.items():
        lines.append(f"## Project: {proj['name']} (`{project_code}`)\n")

        if not proj["connections"]:
            lines.append("_No connections configured._\n")
            continue

        for _conn_id, conn in proj["connections"].items():
            lines.append(f"### Connection: {conn['name']} ({conn['flavor']})\n")

            if not conn["groups"]:
                lines.append("_No table groups._\n")
                continue

            for group_id, group in conn["groups"].items():
                stat = stats_by_group.get(group_id)
                table_ct = stat.table_ct if stat and stat.table_ct else 0
                column_ct = stat.column_ct if stat and stat.column_ct else 0
                group_tables = tables_by_group.get(group_id, [])

                if compact_groups:
                    lines.append(
                        f"- **{group['name']}** (schema: `{group['schema']}`, "
                        f"{table_ct} tables, {column_ct} columns, "
                        f"{len(group['suites'])} test suites)"
                    )
                    continue

                lines.append(
                    f"#### Table Group: {group['name']} (schema: `{group['schema']}`, "
                    f"{table_ct} tables, {column_ct} columns)\n"
                )

                if group_tables:
                    tables_str = ", ".join(f"`{t}`" for t in group_tables)
                    if table_ct and table_ct > 100:
                        tables_str += f", ... ({table_ct - 100} more)"
                    lines.append(f"Tables: {tables_str}\n")

                if not group["suites"]:
                    lines.append("_No test suites._\n")
                    continue

                for suite in group["suites"]:
                    if compact_suites:
                        status_icon = ""
                        if suite["last_run_status"] == "Complete":
                            if suite["failed_ct"]:
                                status_icon = " [FAILURES]"
                            else:
                                status_icon = " [OK]"
                        lines.append(f"- **{suite['name']}** (`{suite['id']}`){status_icon}")
                    else:
                        lines.append(f"**Test Suite: {suite['name']}** (id: `{suite['id']}`)")
                        if suite["last_run_id"]:
                            lines.append(f"  - Last run: `{suite['last_run_id']}` ({suite['last_run_status']})")
                            lines.append(f"  - Time: {suite['last_run_time']}")
                            lines.append(
                                f"  - Results: {suite['test_ct']} tests, "
                                f"{suite['passed_ct']} passed, "
                                f"{suite['failed_ct']} failed, "
                                f"{suite['warning_ct']} warnings"
                            )
                        else:
                            lines.append("  - _No completed runs._")
                        lines.append("")

            lines.append("")

    lines.append(
        "---\n"
        "For test type definitions, read the `testgen://test-types` resource or call `get_test_type`."
    )

    return "\n".join(lines)
