import logging

from testgen.commands.run_get_entities import run_get_connection
from testgen.common import AssignConnectParms, RunActionQueryList
from testgen.common.database.database_service import get_queries_for_command

LOG = logging.getLogger("testgen")


def _get_params_mapping(project_qc_schema: str, user: str) -> dict:
    return {
        "DATA_QC_SCHEMA": project_qc_schema,
        "DB_USER": user,
    }


def run_setup_profiling_tools(
    connection_id: str | int,
    dry_run: bool,
    create_qc_schema: bool = True,
    db_user: str | None = None,
    db_password: str | None = None,
    skip_granting_privileges: bool = False,
) -> str:
    connection = run_get_connection(str(connection_id))

    # Set Project Connection Parms in common.db_bridgers from retrieved parms
    LOG.info("CurrentStep: Assigning Connection Parms")
    user = db_user or connection["project_user"]
    AssignConnectParms(
        connection["project_key"],
        connection["connection_id"],
        connection["project_host"],
        connection["project_port"],
        connection["project_db"],
        connection["project_qc_schema"],
        user,
        connection["sql_flavor"],
        connection["url"],
        connection["connect_by_url"],
        "PROJECT",
    )

    project_qc_schema = connection["project_qc_schema"]
    sql_flavor = connection["sql_flavor"]

    params_mapping = _get_params_mapping(project_qc_schema, connection["project_user"])
    queries = []

    if create_qc_schema:
        queries.extend(
            get_queries_for_command(
                f"flavors/{sql_flavor}/setup_profiling_tools",
                params_mapping,
                mask=rf"^.*create_qc_schema_{sql_flavor}.sql$",
            )
        )

    queries.extend(
        get_queries_for_command(
            f"flavors/{sql_flavor}/setup_profiling_tools", params_mapping, mask=rf"^.*functions_{sql_flavor}.sql$"
        )
    )

    if not skip_granting_privileges:
        queries.extend(
            get_queries_for_command(
                f"flavors/{sql_flavor}/setup_profiling_tools",
                params_mapping,
                mask=rf"^.*grant_execute_privileges_{sql_flavor}.sql$",
            )
        )

    if not dry_run:
        RunActionQueryList("PROJECT", queries, user_override=db_user, pwd_override=db_password)

    return project_qc_schema
