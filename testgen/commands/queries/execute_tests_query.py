import typing

from testgen.common import CleanSQL, date_service, read_template_sql_file


def add_quote_to_identifiers(strInput):
    keywords = [
        "select",
        "from",
        "where",
        "order",
        "by",
        "having",
    ]  # NOTE: In future we might have to expand the list of keywords

    quoted_values = []
    for value in strInput.split(","):
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            quoted_values.append(value)
        elif any(c.isupper() or c.isspace() or value.lower() in keywords for c in value):
            quoted_values.append(f'"{value}"')
        else:
            quoted_values.append(value)
    return ", ".join(quoted_values)


class CTestExecutionSQL:
    flavor = ""
    run_date = ""
    project_code = ""
    test_suite = ""
    test_run_id = ""
    exception_message = ""

    # Test Set Parameters
    dctTestParms: typing.ClassVar = {}
    sum_columns = ""
    match_sum_columns = ""
    multi_column_error_condition = ""

    def __init__(self, strProjectCode, strFlavor, strTestSuite, minutes_offset=0):
        self.project_code = strProjectCode
        self.flavor = strFlavor
        self.test_suite = strTestSuite
        self.today = date_service.get_now_as_string_with_offset(minutes_offset)
        self.minutes_offset = minutes_offset

    def _ReplaceParms(self, strInputString: str):
        strInputString = strInputString.replace("{PROJECT_CODE}", self.project_code)
        strInputString = strInputString.replace("{TEST_SUITE}", self.test_suite)
        strInputString = strInputString.replace("{SQL_FLAVOR}", self.flavor)
        strInputString = strInputString.replace("{TEST_RUN_ID}", self.test_run_id)

        strInputString = strInputString.replace("{RUN_DATE}", self.run_date)
        strInputString = strInputString.replace("{SUM_COLUMNS}", self.sum_columns)
        strInputString = strInputString.replace("{MATCH_SUM_COLUMNS}", self.match_sum_columns)
        strInputString = strInputString.replace("{MULTI_COLUMN_ERROR_CONDITION}", self.multi_column_error_condition)
        strInputString = strInputString.replace("{EXCEPTION_MESSAGE}", self.exception_message)
        strInputString = strInputString.replace("{START_TIME}", self.today)
        strInputString = strInputString.replace(
            "{NOW}", date_service.get_now_as_string_with_offset(self.minutes_offset)
        )

        column_designators = [
            "COLUMN_NAME",
            # "COLUMN_NAMES",
            # "COL_NAME",
            # "COL_NAMES",
            "MATCH_COLUMN_NAMES",
            "MATCH_GROUPBY_NAMES",
            # "MATCH_SUM_COLUMNS",
        ]

        for parm, value in self.dctTestParms.items():
            if value:
                if parm.upper() in column_designators:
                    strInputString = strInputString.replace("{" + parm.upper() + "}", add_quote_to_identifiers(value))
                else:
                    strInputString = strInputString.replace("{" + parm.upper() + "}", value)
            else:
                strInputString = strInputString.replace("{" + parm.upper() + "}", "")
            if parm == "column_name":
                strInputString = strInputString.replace("{COLUMN_NAME_DISPLAY}", value if value else "")

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

        if strTestType in {"AGG MATCH NO DROPS", "AGG MATCH SAME", "AGG MATCH NUM INCR"}:
            self._ConstructAggregateMatchParms()
        strQ = self._GetTestQueryFromTemplate(strTemplate)
        # Final replace to cover parm within CUSTOM_QUERY parm
        strQ = strQ.replace("{DATA_SCHEMA}", self.dctTestParms["schema_name"])

        if booClean:
            strQ = CleanSQL(strQ)
        return strQ
