import logging

from testgen.commands.run_get_entities import run_get_connection
from testgen.common import AssignConnectParms, RunActionQueryList
from testgen.common.database.database_service import get_queries_for_command

LOG = logging.getLogger("testgen")


def _get_params_mapping(project_qc_schema: str, user: str, user_role: str | None) -> dict:
    return {
        "DATA_QC_SCHEMA": project_qc_schema,
        "DB_USER": user,
        "DB_USER_ROLE": user_role,
    }


def get_setup_profiling_tools_queries(sql_flavor, create_qc_schema, skip_granting_privileges, project_qc_schema, user, user_role=None):
    queries = []

    params_mapping = _get_params_mapping(project_qc_schema, user, user_role)

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

    return queries


def run_setup_profiling_tools(
    connection_id: str | int,
    dry_run: bool,
    create_qc_schema: bool = True,
    db_user: str | None = None,
    db_password: str | None = None,
    skip_granting_privileges: bool = False,
    admin_private_key_passphrase: str | None = None,
    admin_private_key: str | None = None,
    user_role: str | None = None,
) -> str:
    connection = run_get_connection(str(connection_id))

    # Set Project Connection Parms in common.db_bridgers from retrieved parms
    LOG.info("CurrentStep: Assigning Connection Parms")
    user = db_user or connection["project_user"]
    connect_by_key = admin_private_key is not None or connection["connect_by_key"]
    private_key_passphrase = admin_private_key_passphrase if admin_private_key is not None else connection["private_key_passphrase"]
    private_key = admin_private_key if admin_private_key is not None else connection["private_key"]

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
        connect_by_key,
        private_key,
        private_key_passphrase,
        "PROJECT",
    )

    project_qc_schema = connection["project_qc_schema"]
    sql_flavor = connection["sql_flavor"]
    user = connection["project_user"]

    queries = get_setup_profiling_tools_queries(sql_flavor, create_qc_schema, skip_granting_privileges, project_qc_schema, user, user_role)

    if not dry_run:
        RunActionQueryList("PROJECT", queries, user_override=db_user, pwd_override=db_password)

    return project_qc_schema
