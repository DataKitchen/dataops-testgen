import logging

import click

from testgen import settings
from testgen.commands.run_get_entities import run_table_group_list
from testgen.commands.run_launch_db_config import run_launch_db_config
from testgen.commands.run_setup_profiling_tools import run_setup_profiling_tools
from testgen.common.database.database_service import (
    AssignConnectParms,
    CreateDatabaseIfNotExists,
    RunActionQueryList,
    replace_params,
)
from testgen.common.read_file import read_template_sql_file

LOG = logging.getLogger("testgen")


def _get_max_date(iteration: int):
    if iteration == 0:
        return "2023-05-31"
    elif iteration == 1:
        return "2023-06-30"
    elif iteration == 2:
        return "2023-07-31"
    elif iteration == 3:
        return "2023-08-30"
    else:
        raise ValueError(f"Unsupported iteration: {iteration}")


def _get_max_customerid_seq(iteration: int):
    if iteration == 0:
        return "100501"
    elif iteration == 1:
        return "100508"
    elif iteration == 2:
        return "100523"
    elif iteration == 3:
        return "100527"
    else:
        raise ValueError(f"Unsupported iteration: {iteration}")


def _get_max_supplierid_seq(iteration: int):
    if iteration == 0:
        return "40027"
    elif iteration == 1:
        return "40031"
    elif iteration == 2:
        return "40036"
    elif iteration == 3:
        return "40039"
    else:
        raise ValueError(f"Unsupported iteration: {iteration}")


def _get_max_productid_seq(iteration: int):
    if iteration == 0:
        return "30041"
    elif iteration == 1:
        return "30045"
    elif iteration == 2:
        return "30049"
    elif iteration == 3:
        return "30054"
    else:
        raise ValueError(f"Unsupported iteration: {iteration}")


def _prepare_connection_to_target_database(params_mapping):
    AssignConnectParms(
        params_mapping["PROJECT_KEY"],
        None,
        params_mapping["PROJECT_DB_HOST"],
        params_mapping["PROJECT_DB_PORT"],
        params_mapping["PROJECT_DB"],
        params_mapping["PROJECT_SCHEMA"],
        params_mapping["TESTGEN_ADMIN_USER"],
        params_mapping["SQL_FLAVOR"],
        None,
        None,
        False,
        None,
        None,
        "PROJECT",
    )


def _get_params_mapping(iteration: int = 0) -> dict:
    return {
        "TESTGEN_ADMIN_USER": settings.DATABASE_ADMIN_USER,
        "TESTGEN_ADMIN_PASSWORD": settings.DATABASE_ADMIN_PASSWORD,
        "PROJECT_DB": settings.PROJECT_DATABASE_NAME,
        "PROJECT_SCHEMA": settings.PROJECT_DATABASE_SCHEMA,
        "PROJECT_KEY": settings.PROJECT_KEY,
        "PROJECT_DB_HOST": settings.PROJECT_DATABASE_HOST,
        "PROJECT_DB_PORT": settings.PROJECT_DATABASE_PORT,
        "SQL_FLAVOR": settings.PROJECT_SQL_FLAVOR,
        "MAX_SUPPLIER_ID_SEQ": _get_max_supplierid_seq(iteration),
        "MAX_PRODUCT_ID_SEQ": _get_max_productid_seq(iteration),
        "MAX_CUSTOMER_ID_SEQ": _get_max_customerid_seq(iteration),
        "MAX_DATE": _get_max_date(iteration),
        "ITERATION_NUMBER": iteration,
    }


def run_quick_start(delete_target_db: bool) -> None:
    # Init
    params_mapping = _get_params_mapping()
    _prepare_connection_to_target_database(params_mapping)

    # Create DB
    target_db_name = params_mapping["PROJECT_DB"]
    click.echo(f"Creating target db : {target_db_name}")
    CreateDatabaseIfNotExists(target_db_name, params_mapping, delete_target_db, drop_users_and_roles=False)

    # run setup
    command = "testgen setup-system-db --delete-db --yes"
    click.echo(f"Running CLI command: {command}")
    delete_db = True
    run_launch_db_config(delete_db)

    # Schema and Populate target db
    click.echo(f"Populating target db : {target_db_name}")
    queries = [
        replace_params(read_template_sql_file("recreate_target_data_schema.sql", "quick_start"), params_mapping),
        replace_params(read_template_sql_file("populate_target_data.sql", "quick_start"), params_mapping),
    ]
    RunActionQueryList(
        "PROJECT",
        queries,
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        pwd_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
    )

    # Get table group id
    project_key = params_mapping["PROJECT_KEY"]
    rows, _ = run_table_group_list(project_key)
    connection_id = str(rows[0][2])

    # run qc
    command = "testgen setup-target-db-functions --connection-id <CONNECTION_ID> --create-qc-schema --yes"
    click.echo(f"Running CLI command: {command}")
    create_qc_schema = True
    db_user = params_mapping["TESTGEN_ADMIN_USER"]
    db_password = params_mapping["TESTGEN_ADMIN_PASSWORD"]
    dry_run = False
    project_qc_schema = run_setup_profiling_tools(connection_id, dry_run, create_qc_schema, db_user, db_password)
    click.echo(f"Schema {project_qc_schema} has been created in the target db")


def run_quick_start_increment(iteration):
    params_mapping = _get_params_mapping(iteration)
    _prepare_connection_to_target_database(params_mapping)

    target_db_name = params_mapping["PROJECT_DB"]
    LOG.info(f"Incremental population of target db : {target_db_name}")

    queries = [
        replace_params(read_template_sql_file("update_target_data.sql", "quick_start"), params_mapping),
    ]
    RunActionQueryList(
        "PROJECT",
        queries,
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        pwd_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
    )
