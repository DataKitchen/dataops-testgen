from typing import ClassVar, TypedDict

from testgen.common import AddQuotesToIdentifierCSV, CleanSQL, ConcatColumnList, date_service, read_template_sql_file
from testgen.common.database.database_service import replace_params


class TestParams(TypedDict):
    test_type: str
    test_definition_id: str
    test_description: str
    test_action: str
    schema_name: str
    table_name: str
    column_name: str
    skip_errors: str
    baseline_ct: str
    baseline_unique_ct: str
    baseline_value: str
    baseline_value_ct: str
    threshold_value: str
    baseline_sum: str
    baseline_avg: str
    baseline_sd: str
    lower_tolerance: str
    upper_tolerance: str
    subset_condition: str
    groupby_names: str
    having_condition: str
    window_date_column: str
    window_days: str
    match_schema_name: str
    match_table_name: str
    match_column_names: str
    match_subset_condition: str
    match_groupby_names: str
    match_having_condition: str
    custom_query: str
    template_name: str


class CTestExecutionSQL:
    flavor = ""
    run_date = ""
    project_code = ""
    test_suite_id = ""
    test_suite = ""
    test_run_id = ""
    exception_message = ""
    process_id = ""
    test_params: ClassVar[TestParams] = {}

    _use_clean = False

    def __init__(self, strProjectCode, strFlavor, strTestSuiteId, strTestSuite, minutes_offset=0):
        self.project_code = strProjectCode
        self.flavor = strFlavor
        self.test_suite_id = strTestSuiteId
        self.test_suite = strTestSuite
        self.today = date_service.get_now_as_string_with_offset(minutes_offset)
        self.minutes_offset = minutes_offset

    def _get_input_parameters(self):
        param_keys = [
            "column_name",
            "skip_errors",
            "baseline_ct",
            "baseline_unique_ct",
            "baseline_value",
            "baseline_value_ct",
            "baseline_sum",
            "baseline_avg",
            "baseline_sd",
            "lower_tolerance",
            "upper_tolerance",
            "subset_condition",
            "groupby_names",
            "having_condition",
            "window_date_column",
            "window_days",
            "match_column_names",
            "match_subset_condition",
            "match_schema_name",
            "match_table_name",
            "match_groupby_names",
            "match_having_condition",
        ]
        input_parameters = "; ".join(
            f"{key}={self.test_params[key]}"
            for key in param_keys
            if key.lower() in self.test_params and self.test_params[key] not in [None, ""]
        )
        return input_parameters.replace("'", "`")

    def _get_query(
        self, template_file_name: str, sub_directory: str | None = "execution", no_bind: bool = False
    ) -> tuple[str, dict | None]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = {
            "PROJECT_CODE": self.project_code,
            "TEST_SUITE_ID": self.test_suite_id,
            "TEST_SUITE": self.test_suite,
            "SQL_FLAVOR": self.flavor,
            "TEST_RUN_ID": self.test_run_id,
            "INPUT_PARAMETERS": self._get_input_parameters(),
            "RUN_DATE": self.run_date,
            "EXCEPTION_MESSAGE": self.exception_message,
            "START_TIME": self.today,
            "PROCESS_ID": self.process_id,
            "VARCHAR_TYPE": "STRING" if self.flavor == "databricks" else "VARCHAR",
            "NOW_TIMESTAMP": date_service.get_now_as_string_with_offset(self.minutes_offset),
            **{key.upper(): value or "" for key, value in self.test_params.items()},
        }

        if self.test_params:
            column_name = self.test_params["column_name"]
            params["COLUMN_NAME"] = AddQuotesToIdentifierCSV(column_name) if column_name else ""
            # Shows contents without double-quotes for display and aggregate expressions
            params["COLUMN_NAME_NO_QUOTES"] = column_name or ""
            # Concatenates column list into single expression for relative entropy
            params["CONCAT_COLUMNS"] = ConcatColumnList(column_name, "<NULL>") if column_name else ""

            match_groupby_names = self.test_params["match_groupby_names"]
            # Concatenates column list into single expression for relative entropy
            params["CONCAT_MATCH_GROUPBY"] = (
                ConcatColumnList(match_groupby_names, "<NULL>") if match_groupby_names else ""
            )

            subset_condition = self.test_params["subset_condition"]
            params["SUBSET_DISPLAY"] = subset_condition.replace("'", "''") if subset_condition else ""

        query = replace_params(query, params)

        if no_bind and self.flavor != "databricks":
            # Adding escape character where ':' is referenced
            query = query.replace(":", "\\:")

        return query, None if no_bind else params

    def GetTestsNonCAT(self) -> tuple[str, dict]:
        # Runs on App database
        query, params = self._get_query("ex_get_tests_non_cat.sql")
        if self._use_clean:
            query = CleanSQL(query)
        return query, params

    def AddTestRecordtoTestRunTable(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_write_test_record_to_testrun_table.sql")

    def PushTestRunStatusUpdateSQL(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("ex_update_test_record_in_testrun_table.sql")

    def GetTestQuery(self) -> tuple[str, None]:
        # Runs on Target database
        if template_name := self.test_params["template_name"]:
            template_flavor = "generic" if template_name.endswith("_generic.sql") else self.flavor
            query, params = self._get_query(template_name, f"flavors/{template_flavor}/exec_query_tests", no_bind=True)
            # Final replace to cover parm within CUSTOM_QUERY parm
            query = replace_params(query, {"DATA_SCHEMA": self.test_params["schema_name"]})

            if self._use_clean:
                query = CleanSQL(query)
            return query, params
        else:
            raise ValueError(f"No query template assigned to test_type {self.test_params["test_type"]}")
