import logging
from typing import ClassVar, TypedDict

from testgen.common import CleanSQL, date_service, read_template_sql_file
from testgen.common.database.database_service import get_queries_for_command, replace_params

LOG = logging.getLogger("testgen")

class GenTestParams(TypedDict):
    test_type: str
    selection_criteria: str
    default_parm_columns: str
    default_parm_values: str


class CDeriveTestsSQL:
    run_date = ""
    project_code = ""
    connection_id = ""
    table_groups_id = ""
    data_schema = ""
    test_suite = ""
    test_suite_id = ""
    generation_set = ""
    as_of_date = ""
    sql_flavor = ""
    gen_test_params: ClassVar[GenTestParams] = {}

    _use_clean = False

    def __init__(self):
        today = date_service.get_now_as_string()
        self.run_date = today
        self.as_of_date = today

    def _get_params(self) -> dict:
        return {
            **{key.upper(): value for key, value in self.gen_test_params.items()},
            "PROJECT_CODE": self.project_code,
            "SQL_FLAVOR": self.sql_flavor,
            "CONNECTION_ID": self.connection_id,
            "TABLE_GROUPS_ID": self.table_groups_id,
            "RUN_DATE": self.run_date,
            "TEST_SUITE": self.test_suite,
            "TEST_SUITE_ID": self.test_suite_id,
            "GENERATION_SET": self.generation_set,
            "AS_OF_DATE": self.as_of_date,
            "DATA_SCHEMA": self.data_schema,
            "ID_SEPARATOR":  "`" if self.sql_flavor == "databricks" else '"',
        }

    def _get_query(self, template_file_name: str, sub_directory: str | None = "generation") -> tuple[str, dict]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = self._get_params()
        query = replace_params(query, params)
        if self._use_clean:
            query = CleanSQL(query)
        return query, params

    def GetInsertTestSuiteSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("gen_insert_test_suite.sql")

    def GetTestTypesSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("gen_standard_test_type_list.sql")

    def GetTestDerivationQueriesAsList(self, template_directory: str) -> list[tuple[str, dict]]:
        # Runs on App database
        params = self._get_params()
        queries = get_queries_for_command(template_directory, params)
        if self._use_clean:
            queries = [ CleanSQL(query) for query in queries ]
        return [ (query, params) for query in queries ]

    def GetTestQueriesFromGenericFile(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("gen_standard_tests.sql")

    def GetDeleteOldTestsQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("gen_delete_old_tests.sql")
