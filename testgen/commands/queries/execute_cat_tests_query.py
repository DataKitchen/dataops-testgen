import typing

from testgen.common import date_service, read_template_sql_file
from testgen.common.database import database_service


class CCATExecutionSQL:
    project_code = ""
    flavor = ""
    concat_operator = ""
    test_suite = ""
    run_date = ""
    test_run_id = ""
    max_query_chars = ""
    exception_message = ""

    # Test Set Parameters
    target_schema = ""
    target_table = ""
    replace_qc_schema = ""
    dctTestParms: typing.ClassVar = {}

    def __init__(self, strProjectCode, strTestSuiteId, strTestSuite, strSQLFlavor, max_query_chars, minutes_offset=0):
        # Defaults
        self.test_suite_id = strTestSuiteId
        self.test_suite = strTestSuite
        self.project_code = strProjectCode
        flavor_service = database_service.get_flavor_service(strSQLFlavor)
        self.concat_operator = flavor_service.get_concat_operator()
        self.flavor = strSQLFlavor
        self.max_query_chars = max_query_chars
        self.today = date_service.get_now_as_string_with_offset(minutes_offset)
        self.minutes_offset = minutes_offset

    def _ReplaceParms(self, strInputString):
        strInputString = strInputString.replace("{MAX_QUERY_CHARS}", str(self.max_query_chars))
        strInputString = strInputString.replace("{TEST_RUN_ID}", self.test_run_id)
        strInputString = strInputString.replace("{PROJECT_CODE}", self.project_code)
        strInputString = strInputString.replace("{TEST_SUITE}", self.test_suite)
        strInputString = strInputString.replace("{TEST_SUITE_ID}", self.test_suite_id)
        # NOTE:  REPLACE_QC_SCHEMA is parm replaced to run build query: sets the actual value to replace.
        #        DATA_QC_SCHEMA is parm in cat_test_conditions that build query replaces via SQL.
        strInputString = strInputString.replace("{REPLACE_QC_SCHEMA}", self.replace_qc_schema)
        strInputString = strInputString.replace("{SQL_FLAVOR}", self.flavor)
        strInputString = strInputString.replace("{CONCAT_OPERATOR}", self.concat_operator)

        strInputString = strInputString.replace("{SCHEMA_NAME}", self.target_schema)
        strInputString = strInputString.replace("{TABLE_NAME}", self.target_table)

        strInputString = strInputString.replace("{RUN_DATE}", self.run_date)
        strInputString = strInputString.replace("{NOW_DATE}", "GETDATE()")
        strInputString = strInputString.replace("{START_TIME}", self.today)
        strInputString = strInputString.replace(
            "{NOW}", date_service.get_now_as_string_with_offset(self.minutes_offset)
        )
        strInputString = strInputString.replace("{EXCEPTION_MESSAGE}", self.exception_message.strip())

        for parm, value in self.dctTestParms.items():
            strInputString = strInputString.replace("{" + parm.upper() + "}", str(value))

        strInputString = strInputString.replace("{RUN_DATE}", self.run_date)

        # Adding escape character where ':' is referenced
        strInputString = strInputString.replace(":", "\\:")

        return strInputString

    def GetDistinctTablesSQL(self):
        # Runs on DK DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_cat_get_distinct_tables.sql", "exec_cat_tests"))
        return strQ

    def GetAggregateTableTestSQL(self):
        # Runs on DK DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_cat_build_agg_table_tests.sql", "exec_cat_tests"))
        return strQ

    def GetAggregateTestParmsSQL(self):
        # Runs on DK DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_cat_retrieve_agg_test_parms.sql", "exec_cat_tests"))
        return strQ

    def PrepCATQuerySQL(self):
        strQ = self._ReplaceParms(read_template_sql_file("ex_cat_test_query.sql", "exec_cat_tests"))
        return strQ

    def GetCATResultsParseSQL(self):
        strQ = self._ReplaceParms(read_template_sql_file("ex_cat_results_parse.sql", "exec_cat_tests"))
        return strQ

    def FinalizeTestResultsSQL(self):
        strQ = self._ReplaceParms(read_template_sql_file("ex_finalize_test_run_results.sql", "execution"))
        return strQ

    def PushTestRunStatusUpdateSQL(self):
        strQ = self._ReplaceParms(read_template_sql_file("ex_update_test_record_in_testrun_table.sql", "execution"))
        return strQ
