import typing

from testgen.common import CleanSQL, date_service, read_template_sql_file
from testgen.common.database.database_service import replace_params


class CTestParamValidationSQL:
    flavor = ""
    run_date = ""
    test_run_id = ""
    test_schemas: str = ""
    message = ""
    test_ids: typing.ClassVar = []
    exception_message = ""
    flag_val = ""

    _use_clean = False

    def __init__(self, strFlavor, strTestSuiteId):
        self.flavor = strFlavor
        self.test_suite_id = strTestSuiteId
        self.today = date_service.get_now_as_string()

    def _get_query(self, template_file_name: str, sub_directory: str | None = "validate_tests") -> tuple[str, dict]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = {
            "TEST_SUITE_ID": self.test_suite_id,
            "RUN_DATE": self.run_date,
            "TEST_RUN_ID": self.test_run_id,
            "FLAG": self.flag_val,
            "TEST_SCHEMAS": self.test_schemas,
            "EXCEPTION_MESSAGE": self.exception_message,
            "MESSAGE": self.message,
            "CAT_TEST_IDS": tuple(self.test_ids or []),
            "START_TIME": self.today,
            "NOW_TIMESTAMP": date_service.get_now_as_string(),
        }
        query = replace_params(query, params)
        return query, params

    def GetTestValidationColumns(self) -> tuple[str, dict]:
        # Runs on App database
        query, params = self._get_query("ex_get_test_column_list_tg.sql")
        if self._use_clean:
            query = CleanSQL(query)
        return query, params

    def GetProjectTestValidationColumns(self) -> tuple[str, dict]:
        # Runs on Target database
        return self._get_query("ex_get_project_column_list_generic.sql", "flavors/generic/validate_tests")

    def PrepFlagTestsWithFailedValidation(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_prep_flag_tests_test_definitions.sql")

    def FlagTestsWithFailedValidation(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_flag_tests_test_definitions.sql")

    def DisableTestsWithFailedValidation(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_disable_tests_test_definitions.sql")

    def ReportTestValidationErrors(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_write_test_val_errors.sql")

    def PushTestRunStatusUpdateSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_update_test_record_in_testrun_table.sql", "execution")
