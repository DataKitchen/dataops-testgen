import logging

import click

from testgen import settings
from testgen.commands.run_launch_db_config import run_launch_db_config
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import (
    create_database,
    execute_db_queries,
    replace_params,
    set_target_db_params,
)
from testgen.common.database.flavor.flavor_service import ConnectionParams
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
    connection_params: ConnectionParams = {
        "sql_flavor": params_mapping["SQL_FLAVOR"],
        "project_host": params_mapping["PROJECT_DB_HOST"],
        "project_port": params_mapping["PROJECT_DB_PORT"],
        "project_db": params_mapping["PROJECT_DB"],
        "project_user": params_mapping["TESTGEN_ADMIN_USER"],
        "table_group_schema": params_mapping["PROJECT_SCHEMA"],
        "project_pw_encrypted": params_mapping["TESTGEN_ADMIN_PASSWORD"],
    }
    set_target_db_params(connection_params)


def _get_params_mapping(iteration: int = 0) -> dict:
    return {
        "TESTGEN_ADMIN_USER": settings.DATABASE_ADMIN_USER,
        "TESTGEN_ADMIN_PASSWORD": settings.DATABASE_ADMIN_PASSWORD,
        "SCHEMA_NAME": get_tg_schema(),
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
    create_database(target_db_name, params_mapping, drop_existing=delete_target_db)

    # run setup
    command = "testgen setup-system-db --delete-db --yes"
    click.echo(f"Running CLI command: {command}")
    delete_db = True
    run_launch_db_config(delete_db)

    # Schema and Populate target db
    click.echo(f"Populating target db : {target_db_name}")
    execute_db_queries(
        [
            (replace_params(read_template_sql_file("recreate_target_data_schema.sql", "quick_start"), params_mapping), params_mapping),
            (replace_params(read_template_sql_file("populate_target_data.sql", "quick_start"), params_mapping), params_mapping),
        ],
        use_target_db=True,
    )


def run_quick_start_increment(iteration):
    params_mapping = _get_params_mapping(iteration)
    _prepare_connection_to_target_database(params_mapping)

    target_db_name = params_mapping["PROJECT_DB"]
    LOG.info(f"Incremental population of target db : {target_db_name}")

    execute_db_queries(
        [
            (replace_params(read_template_sql_file("update_target_data.sql", "quick_start"), params_mapping), params_mapping),
            (replace_params(read_template_sql_file(f"update_target_data_iter{iteration}.sql", "quick_start"), params_mapping), params_mapping),
        ],
        use_target_db=True,
    )
    setup_cat_tests(iteration)


def setup_cat_tests(iteration):
    if iteration == 0:
        return
    elif iteration == 1:
        sql_file = "add_cat_tests.sql"
    elif iteration >=1:
        sql_file = "update_cat_tests.sql"

    params_mapping = _get_params_mapping(iteration)
    query = replace_params(read_template_sql_file(sql_file, "quick_start"), params_mapping)

    execute_db_queries(
        [
            (query, params_mapping),
        ],
        use_target_db=False,
    )
