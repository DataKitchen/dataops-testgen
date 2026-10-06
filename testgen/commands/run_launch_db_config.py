import logging
import os

from testgen import settings
from testgen.common import create_database, execute_db_queries
from testgen.common.credentials import get_tg_db, get_tg_schema
from testgen.common.database.database_service import get_queries_for_command
from testgen.common.encrypt import EncryptText, encrypt_ui_password
from testgen.common.models import with_database_session
from testgen.common.models.user import initial_feedback_popup_seed
from testgen.common.read_file import get_template_files
from testgen.common.read_yaml_metadata_records import import_metadata_records_from_yaml
from testgen.common.standalone_postgres import EMBEDDED_HOST_SENTINEL, is_standalone_mode

LOG = logging.getLogger("testgen")


def _get_latest_revision_number():
    files = sorted(get_template_files(mask=r"^.*sql$", sub_directory="dbupgrade"), key=lambda key: str(key))
    last_file = os.path.basename(str(files[-1]))
    return str(int(last_file.split("_")[0]))  # Drop leading zeroes via str-->int-->str


def _get_params_mapping() -> dict:
    ui_user_encrypted_password = encrypt_ui_password(settings.PASSWORD)

    project_host = settings.PROJECT_DATABASE_HOST
    project_port = settings.PROJECT_DATABASE_PORT
    project_user = settings.PROJECT_DATABASE_USER
    project_password = settings.PROJECT_DATABASE_PASSWORD
    if is_standalone_mode():
        # Live host/port are resolved at connection-build time via the sentinel
        # so the row survives pgserver picking a fresh ephemeral port on Windows.
        project_host = EMBEDDED_HOST_SENTINEL
        project_port = ""
        project_user = "postgres"
        project_password = ""

    return {
        "UI_USER_NAME": settings.USERNAME,
        "UI_USER_USERNAME": settings.USERNAME,
        "UI_USER_EMAIL": "",
        "UI_USER_ENCRYPTED_PASSWORD": ui_user_encrypted_password,
        "LAST_FEEDBACK_POPUP_SEED": initial_feedback_popup_seed(),
        "SCHEMA_NAME": get_tg_schema(),
        "PROJECT_CODE": settings.PROJECT_KEY,
        "CONNECTION_ID": 1,
        "SQL_FLAVOR": settings.PROJECT_SQL_FLAVOR,
        "PROJECT_NAME": settings.PROJECT_NAME,
        "PROJECT_DB": settings.PROJECT_DATABASE_NAME,
        "PROJECT_USER": project_user,
        "PROJECT_PORT": project_port,
        "PROJECT_HOST": project_host,
        "PROJECT_PW_ENCRYPTED": EncryptText(project_password),
        "PROJECT_HTTP_PATH": "",
        "PROJECT_SERVICE_ACCOUNT_KEY": "",
        "PROJECT_SCHEMA": settings.PROJECT_DATABASE_SCHEMA,
        "PROFILING_TABLE_SET": settings.DEFAULT_PROFILING_TABLE_SET,
        "PROFILING_INCLUDE_MASK": settings.DEFAULT_PROFILING_INCLUDE_MASK,
        "PROFILING_EXCLUDE_MASK": settings.DEFAULT_PROFILING_EXCLUDE_MASK,
        "PROFILING_ID_COLUMN_MASK": settings.DEFAULT_PROFILING_ID_COLUMN_MASK,
        "PROFILING_SK_COLUMN_MASK": settings.DEFAULT_PROFILING_SK_COLUMN_MASK,
        "PROFILING_SAMPLE_PERCENT": "",
        "PROFILING_SAMPLE_MIN_COUNT": "",
        "PROFILING_DELAY_DAYS": "",
        "CONNECTION_NAME": settings.PROJECT_CONNECTION_NAME,
        "TABLE_GROUPS_NAME": settings.DEFAULT_TABLE_GROUPS_NAME,
        "TEST_SUITE": settings.DEFAULT_TEST_SUITE_KEY,
        "TEST_SUITE_DESCRIPTION": settings.DEFAULT_TEST_SUITE_DESCRIPTION,
        "MAX_THREADS": settings.PROJECT_CONNECTION_MAX_THREADS,
        "MAX_QUERY_CHARS": settings.PROJECT_CONNECTION_MAX_QUERY_CHAR,
        "OBSERVABILITY_API_URL": settings.OBSERVABILITY_API_URL,
        "OBSERVABILITY_API_KEY": settings.OBSERVABILITY_API_KEY,
        "OBSERVABILITY_COMPONENT_KEY": settings.OBSERVABILITY_DEFAULT_COMPONENT_KEY,
        "OBSERVABILITY_COMPONENT_TYPE": settings.OBSERVABILITY_DEFAULT_COMPONENT_TYPE,
        "TESTGEN_ADMIN_USER": settings.DATABASE_ADMIN_USER,
        "TESTGEN_ADMIN_PASSWORD": settings.DATABASE_ADMIN_PASSWORD,
        "DB_REVISION": _get_latest_revision_number(),
    }


def _quote_identifier(name: str) -> str:
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def _get_app_user_grants(schema: str, admin_user: str | None, app_user: str | None) -> list[str]:
    """Return the statements that let the application user work on objects the admin user owns.

    Args:
        schema: TestGen schema name.
        admin_user: Account that creates and owns the schema objects.
        app_user: Account the application connects with.

    Returns:
        Grants on the existing objects plus default privileges for objects the admin user creates later,
        or an empty list when both accounts are the same.
    """
    if not app_user or app_user == admin_user:
        return []
    grantee = _quote_identifier(app_user)
    return [
        f"GRANT USAGE ON SCHEMA {schema} TO {grantee}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {grantee}",
        f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {schema} TO {grantee}",
        f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {schema} TO {grantee}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {grantee}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {grantee}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT EXECUTE ON FUNCTIONS TO {grantee}",
    ]


def _ensure_app_user_exists(app_user: str, params_mapping: dict) -> None:
    """Raise if the application user is not a role on the database server.

    Args:
        app_user: Account the application connects with.
        params_mapping: Setup parameters holding the admin credentials.
    """
    (role_count,), _ = execute_db_queries(
        [("SELECT COUNT(*) FROM pg_roles WHERE rolname = :role", {"role": app_user})],
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        password_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
        user_type="database_admin",
    )
    if not role_count:
        raise ValueError(f"The database user '{app_user}' set in TG_METADATA_DB_USER does not exist.")


@with_database_session
def run_launch_db_config(delete_db: bool) -> None:
    params_mapping = _get_params_mapping()
    app_user_grants = _get_app_user_grants(
        params_mapping["SCHEMA_NAME"], params_mapping["TESTGEN_ADMIN_USER"], settings.DATABASE_USER
    )
    if app_user_grants:
        _ensure_app_user_exists(settings.DATABASE_USER, params_mapping)

    create_database(get_tg_db(), params_mapping, drop_existing=delete_db)

    queries = get_queries_for_command("dbsetup", params_mapping)
    queries.extend(app_user_grants)

    execute_db_queries(
        [(query, None) for query in queries],
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        password_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
        user_type="schema_admin",
    )
    import_metadata_records_from_yaml(params_mapping)


def get_app_db_params_mapping() -> dict:
    return _get_params_mapping()
