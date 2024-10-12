import typing

from testgen.common import CleanSQL, date_service, read_template_sql_file


class CTestParamValidationSQL:
    flavor = ""
    run_date = ""
    test_run_id = ""
    project_code = ""
    test_suite = ""
    test_schemas = ""
    message = ""
    test_ids = []  # noqa
    exception_message = ""
    flag_val = ""

    # Test Set Parameters
    dctTestParms: typing.ClassVar = {}

    def __init__(self, strFlavor, strTestSuiteId):
        self.flavor = strFlavor
        self.test_suite_id = strTestSuiteId
        self.today = date_service.get_now_as_string()

    def _ReplaceParms(self, strInputString):
        strInputString = strInputString.replace("{TEST_SUITE_ID}", self.test_suite_id)
        strInputString = strInputString.replace("{RUN_DATE}", self.run_date)
        strInputString = strInputString.replace("{TEST_RUN_ID}", self.test_run_id)
        strInputString = strInputString.replace("{FLAG}", self.flag_val)
        strInputString = strInputString.replace("{TEST_SCHEMAS}", self.test_schemas)
        strInputString = strInputString.replace("{EXCEPTION_MESSAGE}", self.exception_message)
        strInputString = strInputString.replace("{MESSAGE}", self.message)
        strInputString = strInputString.replace("{CAT_TEST_IDS}", ", ".join(map(str, self.test_ids)))
        strInputString = strInputString.replace("{START_TIME}", self.today)
        strInputString = strInputString.replace("{NOW}", date_service.get_now_as_string())

        for parm, value in self.dctTestParms.items():
            strInputString = strInputString.replace("{" + parm.upper() + "}", value)

        return strInputString

    def ClearTestParms(self):
        # Test Set Parameters
        pass

    def GetTestValidationColumns(self, booClean):
        # Runs on DK DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_get_test_column_list_tg.sql", "validate_tests"))
        if booClean:
            strQ = CleanSQL(strQ)

        return strQ

    def GetProjectTestValidationColumns(self):
        # Runs on Project DB
        strQ = self._ReplaceParms(
            read_template_sql_file("ex_get_project_column_list_generic.sql", "flavors/generic/validate_tests")
        )

        return strQ

    def PrepFlagTestsWithFailedValidation(self):
        # Runs on Project DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_prep_flag_tests_test_definitions.sql", "validate_tests"))

        return strQ

    def FlagTestsWithFailedValidation(self):
        # Runs on Project DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_flag_tests_test_definitions.sql", "validate_tests"))

        return strQ

    def DisableTestsWithFailedValidation(self):
        # Runs on Project DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_disable_tests_test_definitions.sql", "validate_tests"))

        return strQ

    def ReportTestValidationErrors(self):
        # Runs on Project DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_write_test_val_errors.sql", "validate_tests"))

        return strQ

    def PushTestRunStatusUpdateSQL(self):
        strQ = self._ReplaceParms(read_template_sql_file("ex_update_test_record_in_testrun_table.sql", "execution"))

        return strQ
