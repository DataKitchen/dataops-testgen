import logging

from testgen import settings
from testgen.common import RetrieveSingleResultValue, RunActionQueryList, read_template_sql_file
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import replace_params
from testgen.common.read_file import get_template_files

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

    intNextRevision = RetrieveSingleResultValue("DKTG", strQuery)

    return intNextRevision


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


def _get_upgrade_scripts(sub_directory: str, params_mapping: dict, mask: str = r"^.*sql$", min_val: str = ""):
    files = sorted(get_template_files(mask=mask, sub_directory=sub_directory), key=lambda key: str(key))

    max_prefix = ""
    queries = []
    for file in files:
        if file.name > min_val:
            template = file.read_text("utf-8")
            query = replace_params(template, params_mapping)
            queries.append(query)
            max_prefix = file.name[0:4]

    if len(queries) == 0:
        LOG.debug(f"No sql files were found for the mask {mask} in subdirectory {sub_directory}")

    return queries, max_prefix


def _execute_upgrade_scripts(params_mapping, lstScripts):
    # Run scripts using admin credentials
    RunActionQueryList(
        "DKTG",
        lstScripts,
        "S",
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        pwd_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
    )
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

    RunActionQueryList(
        "DKTG",
        [strQueryMetadata, strQueryViews, strQueryRights],
        "S",
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        pwd_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
    )


def _update_revision_number(params_mapping, latest_prefix_applied):
    # Update extant revision number to highest script prefix applied
    strQuery = read_template_sql_file("080_set_current_revision.sql", "dbsetup")
    strQuery = strQuery.replace("{DB_REVISION}", str(int(latest_prefix_applied)))
    strQuery = replace_params(strQuery, params_mapping)

    RunActionQueryList(
        "DKTG",
        [strQuery],
        "S",
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        pwd_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
    )


def run_upgrade_db_config() -> bool:
    LOG.info("Running run_upgrade_db_config")

    params_mapping = _get_params_mapping()

    # Look for prefix one higher than last revision extant in db
    strNextPrefix = _format_revision_prefix(_get_next_revision_prefix(params_mapping))
    # Retrieve template upgrade directory name
    upgrade_dir = _get_upgrade_template_directory()

    # Retrieve and execute upgrade scripts, if any
    lstQueries, max_prefix = _get_upgrade_scripts(upgrade_dir, params_mapping, min_val=strNextPrefix)
    LOG.info(f"Updating db config qty of queries: {len(lstQueries)}. New prefix: {max_prefix}. Queries: {lstQueries}")
    if len(lstQueries) > 0:
        has_been_upgraded = _execute_upgrade_scripts(params_mapping, lstQueries)
    else:
        has_been_upgraded = False

    _refresh_static_metadata(params_mapping)

    if has_been_upgraded:
        # Update revision number to max prefix found in update scripts
        _update_revision_number(params_mapping, max_prefix)
        LOG.info("Application data was successfully upgraded, and static metadata was refreshed.")
    else:
        LOG.info("Database upgrade was not required. Static metadata was refreshed.")

    return has_been_upgraded


def is_db_revision_up_to_date():
    params_mapping = {"SCHEMA_NAME": get_tg_schema()}
    strNextPrefix = _format_revision_prefix(_get_next_revision_prefix(params_mapping))
    upgrade_dir = _get_upgrade_template_directory()

    # Retrieve and execute upgrade scripts, if any
    lstQueries, max_prefix = _get_upgrade_scripts(upgrade_dir, params_mapping, min_val=strNextPrefix)
    return len(lstQueries) == 0
