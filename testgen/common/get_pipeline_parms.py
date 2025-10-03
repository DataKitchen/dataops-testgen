from typing import TypedDict

from testgen.common.database.database_service import fetch_dict_from_db
from testgen.common.read_file import read_template_sql_file


class BaseParams(TypedDict):
    project_code: str
    connection_id: str

class TestGenerationParams(BaseParams):
    export_to_observability: str
    test_suite_id: str
    profiling_as_of_date: str


class TestExecutionParams(BaseParams):
    test_suite_id: str
    table_groups_id: str
    table_group_schema: str
    profiling_table_set: str
    profiling_include_mask: str
    profiling_exclude_mask: str
    sql_flavor: str
    max_threads: int
    max_query_chars: int


def get_test_generation_params(table_group_id: str, test_suite: str) -> TestGenerationParams:
    results = fetch_dict_from_db(
        read_template_sql_file("parms_test_gen.sql", "parms"),
        {"TABLE_GROUP_ID": table_group_id, "TEST_SUITE": test_suite},
    )
    if not results:
        raise ValueError("Connection parameters not found for test generation.")
    return TestGenerationParams(results[0])


def get_test_execution_params(project_code: str, test_suite: str) -> TestExecutionParams:
    results = fetch_dict_from_db(
        read_template_sql_file("parms_test_execution.sql", "parms"),
        {"PROJECT_CODE": project_code, "TEST_SUITE": test_suite}
    )
    if not results:
        raise ValueError("Connection parameters not found for test execution.")
    return TestExecutionParams(results[0])
