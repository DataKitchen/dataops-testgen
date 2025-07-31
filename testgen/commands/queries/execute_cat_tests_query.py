from typing import ClassVar, TypedDict

from testgen.commands.queries.rollup_scores_query import CRollupScoresSQL
from testgen.common import date_service, read_template_sql_file
from testgen.common.database.database_service import get_flavor_service, replace_params
from testgen.common.read_file import replace_templated_functions


class CATTestParams(TypedDict):
    schema_name: str
    table_name: str
    cat_sequence: int
    test_measures: str
    test_conditions: str


class CCATExecutionSQL:
    project_code = ""
    flavor = ""
    concat_operator = ""
    test_suite = ""
    run_date = ""
    test_run_id = ""
    table_groups_id = ""
    max_query_chars = ""
    exception_message = ""
    target_schema = ""
    target_table = ""
    cat_test_params: ClassVar[CATTestParams] = {}

    _rollup_scores_sql: CRollupScoresSQL = None

    def __init__(self, strProjectCode, strTestSuiteId, strTestSuite, strSQLFlavor, max_query_chars, minutes_offset=0):
        # Defaults
        self.test_suite_id = strTestSuiteId
        self.test_suite = strTestSuite
        self.project_code = strProjectCode
        flavor_service = get_flavor_service(strSQLFlavor)
        self.concat_operator = flavor_service.get_concat_operator()
        self.flavor = strSQLFlavor
        self.max_query_chars = max_query_chars
        self.today = date_service.get_now_as_string_with_offset(minutes_offset)
        self.minutes_offset = minutes_offset

    def _get_rollup_scores_sql(self) -> CRollupScoresSQL:
        if not self._rollup_scores_sql:
            self._rollup_scores_sql = CRollupScoresSQL(self.test_run_id, self.table_groups_id)

        return self._rollup_scores_sql
    
    def _get_query(self, template_file_name: str, sub_directory: str | None = "exec_cat_tests", no_bind: bool = False) -> tuple[str, dict | None]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = {
            "MAX_QUERY_CHARS": self.max_query_chars,
            "TEST_RUN_ID": self.test_run_id,
            "PROJECT_CODE": self.project_code,
            "TEST_SUITE": self.test_suite,
            "TEST_SUITE_ID": self.test_suite_id,
            "TABLE_GROUPS_ID": self.table_groups_id,
            "SQL_FLAVOR": self.flavor,
            "ID_SEPARATOR": "`" if self.flavor == "databricks" else '"',
            "CONCAT_OPERATOR": self.concat_operator,
            "SCHEMA_NAME": self.target_schema,
            "TABLE_NAME": self.target_table,
            "NOW_DATE": "GETDATE()",
            "START_TIME": self.today,
            "NOW_TIMESTAMP": date_service.get_now_as_string_with_offset(self.minutes_offset),
            "EXCEPTION_MESSAGE": self.exception_message.strip(),
            **{key.upper(): value for key, value in self.cat_test_params.items()},
            # This has to be replaced at the end
            "RUN_DATE": self.run_date,
        }
        query = replace_params(query, params)
        query = replace_templated_functions(query, self.flavor)

        if no_bind and self.flavor != "databricks":
            # Adding escape character where ':' is referenced
            query = query.replace(":", "\\:")

        return query, None if no_bind else params

    def GetDistinctTablesSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_cat_get_distinct_tables.sql")

    def GetAggregateTableTestSQL(self) -> tuple[str, None]:
        # Runs on App database
        return self._get_query("ex_cat_build_agg_table_tests.sql", no_bind=True)

    def GetAggregateTestParmsSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_cat_retrieve_agg_test_parms.sql")

    def PrepCATQuerySQL(self) -> tuple[str, None]:
        # Runs on Target database
        return self._get_query("ex_cat_test_query.sql", no_bind=True)

    def GetCATResultsParseSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_cat_results_parse.sql")

    def FinalizeTestResultsSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_finalize_test_run_results.sql", "execution")

    def PushTestRunStatusUpdateSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_update_test_record_in_testrun_table.sql", "execution")

    def FinalizeTestSuiteUpdateSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_update_test_suite.sql", "execution")

    def CalcPrevalenceTestResultsSQL(self) -> tuple[str, None]:
        # Runs on App database
        return self._get_query("ex_calc_prevalence_test_results.sql", "execution", no_bind=True)

    def TestScoringRollupRunSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_rollup_scores_sql().GetRollupScoresTestRunQuery()

    def TestScoringRollupTableGroupSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_rollup_scores_sql().GetRollupScoresTestTableGroupQuery()
