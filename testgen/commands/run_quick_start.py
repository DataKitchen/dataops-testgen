import logging
import random
from datetime import datetime
from typing import Any

import click

from testgen import settings
from testgen.commands.run_launch_db_config import get_app_db_params_mapping, run_launch_db_config
from testgen.commands.test_generation import run_monitor_generation
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import (
    apply_params,
    create_database,
    execute_db_queries,
    set_target_db_params,
)
from testgen.common.database.flavor.flavor_service import ConnectionParams
from testgen.common.models import with_database_session
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.settings import PersistedSetting
from testgen.common.models.table_group import TableGroup
from testgen.common.notifications.base import smtp_configured
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


def _get_settings_params_mapping() -> dict:
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
    }


def _get_quick_start_params_mapping(iteration: int = 0) -> dict:
    return {
        **_get_settings_params_mapping(),
        "MAX_SUPPLIER_ID_SEQ": _get_max_supplierid_seq(iteration),
        "MAX_PRODUCT_ID_SEQ": _get_max_productid_seq(iteration),
        "MAX_CUSTOMER_ID_SEQ": _get_max_customerid_seq(iteration),
        "MAX_DATE": _get_max_date(iteration),
        "ITERATION_NUMBER": iteration,
    }


def _get_monitor_params_mapping(run_date: datetime, iteration: int = 0) -> dict:
    # Volume: linear growth with jitter, spike at specific iteration for anomaly
    random.seed(42)
    if iteration == 37:
        new_sales = 100
    else:
        new_sales = random.randint(8, 12)  # noqa: S311

    # Freshness: update every other iteration, late update for anomaly
    is_update_suppliers_iter = (iteration % 2 == 0 and iteration != 38) or iteration == 39

    return {
        **_get_settings_params_mapping(),
        "ITERATION_NUMBER": iteration,
        "RUN_DATE": run_date,
        "NEW_SALES": new_sales,
        "IS_ADD_CUSTOMER_COL_ITER": iteration == 29,
        "IS_DELETE_CUSTOMER_COL_ITER": iteration == 36,
        "IS_UPDATE_PRODUCT_ITER": not 14 < iteration < 18,
        "IS_CREATE_RETURNS_TABLE_ITER": iteration == 32,
        "IS_DELETE_CUSTOMER_ITER": iteration in (18, 22, 34),
        "IS_UPDATE_SUPPLIERS_ITER": is_update_suppliers_iter,
    }


def _get_quick_start_query(template_file_name: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    template = read_template_sql_file(template_file_name, "quick_start")
    return apply_params(template, params), params


def run_quick_start(delete_target_db: bool) -> None:
    # Init
    params_mapping = _get_quick_start_params_mapping()
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

    click.echo("Seeding the application db")
    app_db_params = get_app_db_params_mapping()
    execute_db_queries(
        [
            _get_quick_start_query("initial_data_seeding.sql", app_db_params),
        ],
    )

    with_database_session(_setup_initial_config)()

    # Schema and Populate target db
    click.echo(f"Populating target db : {target_db_name}")
    execute_db_queries(
        [
            _get_quick_start_query("recreate_target_data_schema.sql", params_mapping),
            _get_quick_start_query("populate_target_data.sql", params_mapping),
        ],
        use_target_db=True,
    )

    score_definition = ScoreDefinition.from_table_group(
        TableGroup(
            project_code=settings.PROJECT_KEY,
            table_groups_name=settings.DEFAULT_TABLE_GROUPS_NAME,
        )
    )
    with_database_session(score_definition.save)()
    with_database_session(run_monitor_generation)("823a1fef-9b6d-48d5-9d0f-2db9812cc318", ["Volume_Trend", "Schema_Drift"])


def _setup_initial_config():
    PersistedSetting.set("SMTP_CONFIGURED", smtp_configured())


def run_quick_start_increment(iteration):
    params_mapping = _get_quick_start_params_mapping(iteration)
    _prepare_connection_to_target_database(params_mapping)

    target_db_name = params_mapping["PROJECT_DB"]
    LOG.info(f"Incremental population of target db : {target_db_name}")

    execute_db_queries(
        [
            _get_quick_start_query("update_target_data.sql", params_mapping),
            _get_quick_start_query(f"update_target_data_iter{iteration}.sql", params_mapping),
        ],
        use_target_db=True,
    )
    setup_cat_tests(iteration)


def run_monitor_increment(run_date, iteration):
    params_mapping = _get_monitor_params_mapping(run_date, iteration)
    _prepare_connection_to_target_database(params_mapping)

    target_db_name = params_mapping["PROJECT_DB"]
    LOG.info(f"Incremental monitor updates of target db ({iteration}) : {target_db_name}")

    execute_db_queries(
        [
            _get_quick_start_query("run_monitor_iteration.sql", params_mapping),
        ],
        use_target_db=True,
    )


def setup_cat_tests(iteration):
    if iteration == 0:
        return
    elif iteration == 1:
        sql_file = "add_cat_tests.sql"
    elif iteration >=1:
        sql_file = "update_cat_tests.sql"

    params_mapping = _get_quick_start_params_mapping(iteration)

    execute_db_queries(
        [
            _get_quick_start_query(sql_file, params_mapping),
        ],
        use_target_db=False,
    )
