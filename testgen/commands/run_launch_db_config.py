import logging
import os

from testgen import settings
from testgen.common import CreateDatabaseIfNotExists, RunActionQueryList, date_service
from testgen.common.credentials import get_tg_db, get_tg_schema
from testgen.common.database.database_service import get_queries_for_command
from testgen.common.encrypt import EncryptText, encrypt_ui_password
from testgen.common.read_file import get_template_files

LOG = logging.getLogger("testgen")


def _get_latest_revision_number():
    files = sorted(get_template_files(mask=r"^.*sql$", sub_directory="dbupgrade"), key=lambda key: str(key))
    last_file = os.path.basename(str(files[-1]))
    return str(int(last_file.split("_")[0]))  # Drop leading zeroes via str-->int-->str


def _get_params_mapping() -> dict:
    ui_user_encrypted_password = encrypt_ui_password(settings.PASSWORD)

    now = date_service.get_now_as_string()
    return {
        "UI_USER_NAME": settings.USERNAME,
        "UI_USER_USERNAME": settings.USERNAME,
        "UI_USER_EMAIL": "",
        "UI_USER_ENCRYPTED_PASSWORD": ui_user_encrypted_password,
        "SCHEMA_NAME": get_tg_schema(),
        "START_DATE": now,
        "PROJECT_CODE": settings.PROJECT_KEY,
        "CONNECTION_ID": 1,
        "SQL_FLAVOR": settings.PROJECT_SQL_FLAVOR,
        "PROJECT_NAME": settings.PROJECT_NAME,
        "PROJECT_DB": settings.PROJECT_DATABASE_NAME,
        "PROJECT_USER": settings.PROJECT_DATABASE_USER,
        "PROJECT_PORT": settings.PROJECT_DATABASE_PORT,
        "PROJECT_HOST": settings.PROJECT_DATABASE_HOST,
        "PROJECT_SCHEMA": settings.PROJECT_DATABASE_SCHEMA,
        "PROFILING_TABLE_SET": settings.DEFAULT_PROFILING_TABLE_SET,
        "PROFILING_INCLUDE_MASK": settings.DEFAULT_PROFILING_INCLUDE_MASK,
        "PROFILING_EXCLUDE_MASK": settings.DEFAULT_PROFILING_EXCLUDE_MASK,
        "PROFILING_ID_COLUMN_MASK": settings.DEFAULT_PROFILING_ID_COLUMN_MASK,
        "PROFILING_SK_COLUMN_MASK": settings.DEFAULT_PROFILING_SK_COLUMN_MASK,
        "PROFILING_USE_SAMPLING": settings.DEFAULT_PROFILING_USE_SAMPLING,
        "PROFILING_SAMPLE_PERCENT": "",
        "PROFILING_SAMPLE_MIN_COUNT": "",
        "PROFILING_DELAY_DAYS": "",
        "CONNECTION_NAME": settings.PROJECT_CONNECTION_NAME,
        "PROJECT_QC_SCHEMA": settings.PROJECT_QC_SCHEMA,
        "TABLE_GROUPS_NAME": settings.DEFAULT_TABLE_GROUPS_NAME,
        "TEST_SUITE": settings.DEFAULT_TEST_SUITE_KEY,
        "TEST_SUITE_DESCRIPTION": settings.DEFAULT_TEST_SUITE_DESCRIPTION,
        "MAX_THREADS": settings.PROJECT_CONNECTION_MAX_THREADS,
        "MAX_QUERY_CHARS": settings.PROJECT_CONNECTION_MAX_QUERY_CHAR,
        "PROJECT_PW_ENCRYPTED": EncryptText(settings.PROJECT_DATABASE_PASSWORD),
        "OBSERVABILITY_API_URL": settings.OBSERVABILITY_API_URL,
        "OBSERVABILITY_API_KEY": settings.OBSERVABILITY_API_KEY,
        "OBSERVABILITY_COMPONENT_KEY": settings.OBSERVABILITY_DEFAULT_COMPONENT_KEY,
        "OBSERVABILITY_COMPONENT_TYPE": settings.OBSERVABILITY_DEFAULT_COMPONENT_TYPE,
        "TESTGEN_ADMIN_USER": settings.DATABASE_ADMIN_USER,
        "TESTGEN_ADMIN_PASSWORD": settings.DATABASE_ADMIN_PASSWORD,
        "TESTGEN_USER": settings.DATABASE_EXECUTE_USER,
        "TESTGEN_PASSWORD": settings.DATABASE_PASSWORD,
        "TESTGEN_REPORT_USER": settings.DATABASE_REPORT_USER,
        "TESTGEN_REPORT_PASSWORD": settings.DATABASE_PASSWORD,
        "DB_REVISION": _get_latest_revision_number(),
    }


def run_launch_db_config(delete_db: bool) -> None:
    params_mapping = _get_params_mapping()

    CreateDatabaseIfNotExists(get_tg_db(), params_mapping, delete_db)

    queries = get_queries_for_command("dbsetup", params_mapping)

    RunActionQueryList(
        "DKTG",
        queries,
        "S",
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        pwd_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
    )
