import logging

from testgen.common import RetrieveDBResultsToList, read_template_sql_file
from testgen.common.encrypt import DecryptText

LOG = logging.getLogger("testgen")


def run_list_profiles(table_groups_id):
    sql_template = read_template_sql_file("get_profile_list.sql", "get_entities")

    sql_template = sql_template.replace("{TABLE_GROUPS_ID}", table_groups_id)

    return RetrieveDBResultsToList("DKTG", sql_template)


def run_list_test_types():
    sql_template = read_template_sql_file("list_test_types.sql", "get_entities")
    return RetrieveDBResultsToList("DKTG", sql_template)


def run_list_projects():
    sql_template = read_template_sql_file("get_project_list.sql", "get_entities")
    return RetrieveDBResultsToList("DKTG", sql_template)


def run_list_connections():
    sql_template = read_template_sql_file("get_connections_list.sql", "get_entities")
    return RetrieveDBResultsToList("DKTG", sql_template)


def run_get_connection(connection_id):
    sql_template = read_template_sql_file("get_connection.sql", "get_entities")
    sql_template = sql_template.replace("{CONNECTION_ID}", str(connection_id))
    rows, _ = RetrieveDBResultsToList("DKTG", sql_template)
    connection = rows.pop()._asdict()
    connection["password"] = DecryptText(connection["project_pw_encrypted"]) if connection["project_pw_encrypted"] else None
    connection["private_key"] = DecryptText(connection["private_key"]) if connection["private_key"] else None
    connection["private_key_passphrase"] = DecryptText(connection["private_key_passphrase"]) if connection["private_key_passphrase"] else ""
    return connection


def run_table_group_list(project_code):
    sql_template = read_template_sql_file("get_table_group_list.sql", "get_entities")
    sql_template = sql_template.replace("{PROJECT_CODE}", project_code)
    return RetrieveDBResultsToList("DKTG", sql_template)


def run_list_test_suites(project_code):
    sql_template = read_template_sql_file("get_test_suite_list.sql", "get_entities")
    sql_template = sql_template.replace("{PROJECT_CODE}", project_code)
    return RetrieveDBResultsToList("DKTG", sql_template)


def run_get_test_suite(project_code, test_suite):
    sql_template = read_template_sql_file("get_test_suite.sql", "get_entities")

    sql_template = sql_template.replace("{PROJECT_CODE}", project_code)
    sql_template = sql_template.replace("{TEST_SUITE}", test_suite)

    return RetrieveDBResultsToList("DKTG", sql_template)


def run_profile_info(profile_run, table_name=None):
    if not table_name:
        table_name = "%"  # if no table_name, we select all the tables
    sql_template = read_template_sql_file("get_profile_info.sql", "get_entities")

    sql_template = sql_template.replace("{PROFILE_RUN}", str(profile_run))
    sql_template = sql_template.replace("{TABLE_NAME}", table_name)

    return RetrieveDBResultsToList("DKTG", sql_template)


def run_profile_screen(profile_run, table_name=None):
    if not table_name:
        table_name = "%"
    sql_template = read_template_sql_file("get_profile_screen.sql", "get_entities")

    sql_template = sql_template.replace("{PROFILE_RUN}", profile_run)
    sql_template = sql_template.replace("{TABLE_NAME}", table_name)

    return RetrieveDBResultsToList("DKTG", sql_template)


def run_list_test_generation(project_code, test_suite):
    sql_template = read_template_sql_file("get_test_generation_list.sql", "get_entities")

    sql_template = sql_template.replace("{PROJECT_CODE}", project_code)
    sql_template = sql_template.replace("{TEST_SUITE}", test_suite)

    return RetrieveDBResultsToList("DKTG", sql_template)


def run_test_info(project_code, test_suite):
    sql_template = read_template_sql_file("get_test_info.sql", "get_entities")

    sql_template = sql_template.replace("{PROJECT_CODE}", project_code)
    sql_template = sql_template.replace("{TEST_SUITE}", test_suite)

    return RetrieveDBResultsToList("DKTG", sql_template)


def run_list_test_runs(project_code, test_suite):
    sql_template = read_template_sql_file("get_test_run_list.sql", "get_entities")

    sql_template = sql_template.replace("{PROJECT_CODE}", project_code)
    sql_template = sql_template.replace("{TEST_SUITE}", test_suite)

    return RetrieveDBResultsToList("DKTG", sql_template)


def run_get_results(test_run_id, booErrorsOnly):
    sql_template = read_template_sql_file("get_test_results_for_run_cli.sql", "get_entities")

    sql_template = sql_template.replace("{TEST_RUN_ID}", test_run_id)
    if booErrorsOnly:
        sql_template = sql_template.replace("{ERRORS_ONLY}", "AND result_code = 0")
    else:
        sql_template = sql_template.replace("{ERRORS_ONLY}", "")

    return RetrieveDBResultsToList("DKTG", sql_template)
