import logging

from testgen import settings
from testgen.common import execute_db_queries, fetch_dict_from_db, read_template_sql_file
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import replace_params
from testgen.common.read_file import get_template_files
from testgen.common.read_yaml_metadata_records import import_metadata_records_from_yaml

LOG = logging.getLogger("testgen")


def _get_params_mapping() -> dict:
    return {
        "SCHEMA_NAME": get_tg_schema(),
        "TESTGEN_ADMIN_USER": settings.DATABASE_ADMIN_USER,
        "TESTGEN_ADMIN_PASSWORD": settings.DATABASE_ADMIN_PASSWORD,
        "OBSERVABILITY_URL": settings.OBSERVABILITY_API_URL,
    }


def _get_revision_prefix(params_mapping):
    strQuery = read_template_sql_file("get_tg_revision.sql", "dbupgrade_helpers")
    strQuery = replace_params(strQuery, params_mapping)

    result = fetch_dict_from_db(strQuery)
    return result[0]["revision"]


def _get_next_revision_prefix(params_mapping):
    return _get_revision_prefix(params_mapping) + 1


def get_schema_revision():
    params_mapping = {"SCHEMA_NAME": get_tg_schema()}
    try:
        schema_revision = str(_get_revision_prefix(params_mapping))
    except Exception:
        schema_revision = "UNKNOWN"
    return schema_revision


def _format_revision_prefix(intNextRevision: int):
    if intNextRevision < 1 or intNextRevision > 9999:
        raise ValueError(f"The prefix {intNextRevision} for the upgrade script is out of range.")

    return str(intNextRevision).zfill(4)


def _get_upgrade_template_directory():
    return "dbupgrade"


def _get_upgrade_scripts(sub_directory: str, params_mapping: dict, mask: str = r"^.*sql$", min_val: str = "") -> list[tuple[str, str]]:
    files = sorted(get_template_files(mask=mask, sub_directory=sub_directory), key=lambda key: str(key))

    scripts = []
    for file in files:
        if file.name > min_val:
            template = file.read_text("utf-8")
            query = replace_params(template, params_mapping)
            scripts.append((file.name[0:4], query))

    if not scripts:
        LOG.debug(f"No sql files were found for the mask {mask} in subdirectory {sub_directory}")

    return scripts


def _split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements on semicolons.

    Handles the common DDL patterns in upgrade scripts. Does not handle
    dollar-quoted PL/pgSQL blocks — upgrade scripts should not contain those.
    Strips SET SEARCH_PATH lines since upgrade scripts use fully-qualified names.
    """
    statements = []
    for raw in sql.split(";"):
        stmt = raw.strip()
        if not stmt:
            continue
        # SET SEARCH_PATH is handled by the connection; skip it
        if stmt.upper().startswith("SET SEARCH_PATH"):
            continue
        # Strip inline comments from otherwise-empty lines
        lines = [ln for ln in stmt.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        if lines:
            statements.append(stmt)
    return statements


def _execute_upgrade_scripts(params_mapping: dict, scripts: list[tuple[str, str]]) -> bool:
    admin_user = params_mapping["TESTGEN_ADMIN_USER"]
    admin_password = params_mapping["TESTGEN_ADMIN_PASSWORD"]

    for revision_prefix, query in scripts:
        LOG.info(f"Applying upgrade script {revision_prefix}")
        statements = _split_sql_statements(query)
        execute_db_queries(
            [(stmt, None) for stmt in statements],
            user_override=admin_user,
            password_override=admin_password,
            user_type="schema_admin",
        )
        _update_revision_number(params_mapping, revision_prefix)

    return True


def _refresh_static_metadata(params_mapping):
    # Refresh static metadata -- shouldn't affect user data
    strQueryMetadata = read_template_sql_file("050_populate_new_schema_metadata.sql", "dbsetup")
    strQueryMetadata = replace_params(strQueryMetadata, params_mapping)
    # Recreate standard views
    strQueryViews = read_template_sql_file("060_create_standard_views.sql", "dbsetup")
    strQueryViews = replace_params(strQueryViews, params_mapping)
    # Reassign rights to standard roles
    strQueryRights = read_template_sql_file("075_grant_role_rights.sql", "dbsetup")
    strQueryRights = replace_params(strQueryRights, params_mapping)

    execute_db_queries(
        [(strQueryMetadata, None), (strQueryViews, None), (strQueryRights, None)],
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        password_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
        user_type="schema_admin",
    )
    import_metadata_records_from_yaml(params_mapping)

    strQueryMetadataConstraints = read_template_sql_file("055_recreate_metadata_constraints.sql", "dbsetup")
    strQueryMetadataConstraints = replace_params(strQueryMetadataConstraints, params_mapping)
    execute_db_queries(
        [(strQueryMetadataConstraints, None)],
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        password_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
        user_type="schema_admin",
    )


def _update_revision_number(params_mapping, latest_prefix_applied):
    # Update extant revision number to highest script prefix applied
    strQuery = read_template_sql_file("080_set_current_revision.sql", "dbsetup")
    strQuery = strQuery.replace("{DB_REVISION}", str(int(latest_prefix_applied)))
    strQuery = replace_params(strQuery, params_mapping)

    execute_db_queries(
        [(strQuery, None)],
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        password_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
        user_type="schema_admin",
    )


def run_upgrade_db_config() -> bool:
    LOG.info("Upgrading system version")
    params_mapping = _get_params_mapping()
    current_revision = _get_revision_prefix(params_mapping)

    next_revision = _format_revision_prefix(_get_next_revision_prefix(params_mapping))
    upgrade_dir = _get_upgrade_template_directory()

    scripts = _get_upgrade_scripts(upgrade_dir, params_mapping, min_val=next_revision)
    latest_revision = scripts[-1][0] if scripts else current_revision
    LOG.info(f"Current revision: {current_revision}. Latest revision: {latest_revision}. Upgrade scripts: {len(scripts)}")
    if scripts:
        _execute_upgrade_scripts(params_mapping, scripts)

    LOG.info("Refreshing static metadata")
    _refresh_static_metadata(params_mapping)

    has_been_upgraded = bool(scripts)
    if has_been_upgraded:
        LOG.info("Application data was successfully upgraded, and static metadata was refreshed.")
    else:
        LOG.info("Database upgrade was not required. Static metadata was refreshed.")

    return has_been_upgraded


def is_db_revision_up_to_date():
    params_mapping = {"SCHEMA_NAME": get_tg_schema()}
    strNextPrefix = _format_revision_prefix(_get_next_revision_prefix(params_mapping))
    upgrade_dir = _get_upgrade_template_directory()

    scripts = _get_upgrade_scripts(upgrade_dir, params_mapping, min_val=strNextPrefix)
    return len(scripts) == 0
