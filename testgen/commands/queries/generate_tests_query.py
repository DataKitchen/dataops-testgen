import logging
from datetime import UTC, datetime
from typing import ClassVar, TypedDict

from testgen.common import CleanSQL, read_template_sql_file
from testgen.common.database.database_service import get_flavor_service, replace_params
from testgen.common.read_file import get_template_files

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

    def __init__(self, flavor):
        self.sql_flavor = flavor
        self.flavor_service = get_flavor_service(flavor)

        today = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
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
            "QUOTE": self.flavor_service.quote_character,
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
        generic_template_directory = template_directory
        flavor_template_directory = f"flavors.{self.sql_flavor}.{template_directory}"

        query_templates = {}
        try:
            for query_file in get_template_files(r"^.*sql$", generic_template_directory):
                query_templates[query_file.name] = generic_template_directory
        except:
            LOG.debug(
                f"query template '{generic_template_directory}' directory does not exist",
                exc_info=True,
                stack_info=True,
            )

        try:
            for query_file in get_template_files(r"^.*sql$", flavor_template_directory):
                query_templates[query_file.name] = flavor_template_directory
        except:
            LOG.debug(
                f"query template '{generic_template_directory}' directory does not exist",
                exc_info=True,
                stack_info=True,
            )

        queries = []
        for filename, sub_directory in query_templates.items():
            queries.append(self._get_query(filename, sub_directory=sub_directory))

        return queries

    def GetTestQueriesFromGenericFile(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("gen_standard_tests.sql")

    def GetDeleteOldTestsQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("gen_delete_old_tests.sql")
