import typing

from testgen.common import AddQuotesToIdentifierCSV, CleanSQL, ConcatColumnList, date_service, read_template_sql_file


class CTestExecutionSQL:
    flavor = ""
    run_date = ""
    project_code = ""
    test_suite_id = ""
    test_suite = ""
    test_run_id = ""
    exception_message = ""
    process_id = ""

    # Test Group Parameters
    dctTestParms: typing.ClassVar = {}
    sum_columns = ""
    match_sum_columns = ""
    multi_column_error_condition = ""

    def __init__(self, strProjectCode, strFlavor, strTestSuiteId, strTestSuite, minutes_offset=0):
        self.project_code = strProjectCode
        self.flavor = strFlavor
        self.test_suite_id = strTestSuiteId
        self.test_suite = strTestSuite
        self.today = date_service.get_now_as_string_with_offset(minutes_offset)
        self.minutes_offset = minutes_offset

    def _AssembleDisplayParameters(self):

        lst_parms = ["column_name", "skip_errors", "baseline_ct", "baseline_unique_ct", "baseline_value",
                     "baseline_value_ct", "baseline_sum", "baseline_avg", "baseline_sd", "subset_condition",
                     "groupby_names", "having_condition", "window_date_column", "window_days",
                     "match_column_names", "match_subset_condition", "match_schema_name", "match_table_name",
                     "match_groupby_names", "match_having_condition",
                     ]
        str_parms = "; ".join(f"{key}={self.dctTestParms[key]}"
                             for key in lst_parms
                             if key.lower() in self.dctTestParms and self.dctTestParms[key] not in [None, ""])
        str_parms = str_parms.replace("'", "`")
        return str_parms

    def _ReplaceParms(self, strInputString: str):
        strInputString = strInputString.replace("{PROJECT_CODE}", self.project_code)
        strInputString = strInputString.replace("{TEST_SUITE_ID}", self.test_suite_id)
        strInputString = strInputString.replace("{TEST_SUITE}", self.test_suite)
        strInputString = strInputString.replace("{SQL_FLAVOR}", self.flavor)
        strInputString = strInputString.replace("{TEST_RUN_ID}", self.test_run_id)
        strInputString = strInputString.replace("{INPUT_PARAMETERS}", self._AssembleDisplayParameters())

        strInputString = strInputString.replace("{RUN_DATE}", self.run_date)
        strInputString = strInputString.replace("{EXCEPTION_MESSAGE}", self.exception_message)
        strInputString = strInputString.replace("{START_TIME}", self.today)
        strInputString = strInputString.replace("{PROCESS_ID}", str(self.process_id))
        strInputString = strInputString.replace(
            "{NOW}", date_service.get_now_as_string_with_offset(self.minutes_offset)
        )

        column_designators = [
            "COLUMN_NAME",
            # "COLUMN_NAMES",
            # "COL_NAME",
            # "COL_NAMES",
            # "MATCH_COLUMN_NAMES",
            # "MATCH_GROUPBY_NAMES",
            # "MATCH_SUM_COLUMNS",
        ]

        for parm, value in self.dctTestParms.items():
            if value:
                if parm.upper() in column_designators:
                    strInputString = strInputString.replace("{" + parm.upper() + "}", AddQuotesToIdentifierCSV(value))
                else:
                    strInputString = strInputString.replace("{" + parm.upper() + "}", value)
            else:
                strInputString = strInputString.replace("{" + parm.upper() + "}", "")
            if parm == "column_name":
                # Shows contents without double-quotes for display and aggregate expressions
                strInputString = strInputString.replace("{COLUMN_NAME_NO_QUOTES}", value if value else "")
                # Concatenates column list into single expression for relative entropy
                str_value = ConcatColumnList(value, "<NULL>")
                strInputString = strInputString.replace("{CONCAT_COLUMNS}", str_value if str_value else "")
            if parm == "match_groupby_names":
                # Concatenates column list into single expression for relative entropy
                str_value = ConcatColumnList(value, "<NULL>")
                strInputString = strInputString.replace("{CONCAT_MATCH_GROUPBY}", str_value if str_value else "")
            if parm == "subset_condition":
                strInputString = strInputString.replace("{SUBSET_DISPLAY}", value.replace("'", "''") if value else "")


        # Adding escape character where ':' is referenced
        strInputString = strInputString.replace(":", "\\:")

        return strInputString

    def ClearTestParms(self):
        # Test Set Parameters
        pass

    def GetTestsNonCAT(self, booClean):
        # Runs on DK DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_get_tests_non_cat.sql", "execution"))
        if booClean:
            strQ = CleanSQL(strQ)

        return strQ

    def AddTestRecordtoTestRunTable(self):
        strQ = self._ReplaceParms(read_template_sql_file("ex_write_test_record_to_testrun_table.sql", "execution"))

        return strQ

    def PushTestRunStatusUpdateSQL(self):
        # Runs on DK DB
        strQ = self._ReplaceParms(read_template_sql_file("ex_update_test_record_in_testrun_table.sql", "execution"))

        return strQ

    def _GetTestQueryFromTemplate(self, strTemplateFile: str):
        # Runs on Project DB
        if strTemplateFile.endswith("_generic.sql"):
            template_flavor = "generic"
        else:
            template_flavor = self.flavor
        strQ = self._ReplaceParms(
            read_template_sql_file(strTemplateFile, f"flavors/{template_flavor}/exec_query_tests")
        )
        return strQ

    def _ConstructAggregateMatchParms(self):
        # Prepares column list for SQL to compare sums of each column

        # Split each comma separated column name into individual list items
        cols = [s.strip() for s in self.dctTestParms["column_name"].split(",")]
        _ = [s.strip() for s in self.dctTestParms["match_column_names"].split(",")]

        # Surround all column names with SUM() to generate proper SQL syntax
        self.list_sum_columns = ["SUM(" + i + ") as " + i for i in cols]
        self.sum_columns = ", ".join(self.list_sum_columns)

        self.list_match_sum_columns = ["SUM(" + i + ") as " + i for i in cols]
        self.match_sum_columns = ", ".join(self.list_match_sum_columns)

        # Suffix all column names with '< 0' to generate proper SQL WHERE/HAVING clause syntax
        self.list_multi_column_error_condition = [i + " < 0" for i in cols]
        self.multi_column_error_condition = " or ".join(self.list_multi_column_error_condition)


    def GetTestQuery(self, booClean: bool):
        strTestType = self.dctTestParms["test_type"]
        strTemplate = self.dctTestParms["template_name"]

        if strTemplate == "":
            raise ValueError(f"No query template assigned to test_type {strTestType}")

        strQ = self._GetTestQueryFromTemplate(strTemplate)
        # Final replace to cover parm within CUSTOM_QUERY parm
        strQ = strQ.replace("{DATA_SCHEMA}", self.dctTestParms["schema_name"])

        if booClean:
            strQ = CleanSQL(strQ)
        return strQ
