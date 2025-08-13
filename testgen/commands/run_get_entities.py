from testgen.common import fetch_list_from_db, read_template_sql_file


def run_list_profiles(table_group_id: str):
    return fetch_list_from_db(
        read_template_sql_file("get_profile_list.sql", "get_entities"),
        {"TABLE_GROUP_ID": table_group_id},
    )


def run_list_test_types():
    sql_template = read_template_sql_file("list_test_types.sql", "get_entities")
    return fetch_list_from_db(sql_template)


def run_list_projects():
    sql_template = read_template_sql_file("get_project_list.sql", "get_entities")
    return fetch_list_from_db(sql_template)


def run_list_connections():
    sql_template = read_template_sql_file("get_connections_list.sql", "get_entities")
    return fetch_list_from_db(sql_template)


def run_table_group_list(project_code):
    sql_template = read_template_sql_file("get_table_group_list.sql", "get_entities")
    return fetch_list_from_db(sql_template, {"PROJECT_CODE": project_code})


def run_list_test_suites(project_code):
    sql_template = read_template_sql_file("get_test_suite_list.sql", "get_entities")
    return fetch_list_from_db(sql_template, {"PROJECT_CODE": project_code})


def run_get_test_suite(project_code: str, test_suite: str):
    return fetch_list_from_db(
        read_template_sql_file("get_test_suite.sql", "get_entities"),
        {"PROJECT_CODE": project_code, "TEST_SUITE": test_suite},
    )


def run_profile_info(profiling_run_id: str, table_name: str | None = None):
    return fetch_list_from_db(
        read_template_sql_file("get_profile_info.sql", "get_entities"),
        # if no table_name, we select all the tables
        {"PROFILING_RUN_ID": profiling_run_id, "TABLE_NAME": table_name or "%"},
    )


def run_profile_screen(profiling_run_id: str, table_name: str | None = None):
    return fetch_list_from_db(
        read_template_sql_file("get_profile_screen.sql", "get_entities"),
        # if no table_name, we select all the tables
        {"PROFILING_RUN_ID": profiling_run_id, "TABLE_NAME": table_name or "%"},
    )


def run_list_test_generation(project_code: str, test_suite: str):
    return fetch_list_from_db(
        read_template_sql_file("get_test_generation_list.sql", "get_entities"),
        {"PROJECT_CODE": project_code, "TEST_SUITE": test_suite},
    )


def run_test_info(project_code: str, test_suite: str):
    return fetch_list_from_db(
        read_template_sql_file("get_test_info.sql", "get_entities"),
        {"PROJECT_CODE": project_code, "TEST_SUITE": test_suite},
    )


def run_list_test_runs(project_code: str, test_suite: str):
    return fetch_list_from_db(
        read_template_sql_file("get_test_run_list.sql", "get_entities"),
        {"PROJECT_CODE": project_code, "TEST_SUITE": test_suite},
    )


def run_get_results(test_run_id: str, errors_only: bool):
    sql_template = read_template_sql_file("get_test_results_for_run_cli.sql", "get_entities")
    sql_template = sql_template.replace("{ERRORS_ONLY}", "AND result_code = 0" if errors_only else "")
    return fetch_list_from_db(sql_template, {"TEST_RUN_ID": test_run_id})
