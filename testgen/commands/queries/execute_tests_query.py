import dataclasses
from collections.abc import Iterable
from datetime import datetime
from typing import TypedDict
from uuid import UUID

from testgen.common import read_template_sql_file
from testgen.common.clean_sql import concat_columns
from testgen.common.database.database_service import get_flavor_service, get_tg_schema, replace_params
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestRunType, TestScope
from testgen.common.models.test_run import TestRun
from testgen.common.read_file import replace_templated_functions


@dataclasses.dataclass
class InputParameters:
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

@dataclasses.dataclass
class TestExecutionDef(InputParameters):
    id: UUID
    test_type: str
    schema_name: str
    table_name: str
    column_name: str
    skip_errors: int
    custom_query: str
    run_type: TestRunType
    test_scope: TestScope
    template_name: str
    measure: str
    test_operator: str
    test_condition: str
    # Runtime attributes
    column_type: str = None
    measure_expression: str = None
    condition_expression: str = None
    errors: list[str] = dataclasses.field(default_factory=list)

class AggregateResult(TypedDict):
    query_index: int
    result_measures: str
    result_codes: str


class TestExecutionSQL:

    null_value = "<NULL>"
    test_results_table = "test_results"
    result_columns = (
        "test_run_id",
        "test_suite_id",
        "test_time",
        "test_definition_id",
        "test_type",
        "schema_name",
        "table_name",
        "column_names",
        "skip_errors",
        "input_parameters",
        "result_code",
        "result_status",
        "result_message",
        "result_measure",
    )

    def __init__(self, connection: Connection, table_group: TableGroup, test_run: TestRun):
        self.connection = connection
        self.table_group = table_group
        self.test_run = test_run
        self.run_date = test_run.test_starttime.strftime("%Y-%m-%d %H:%M:%S")
        self.flavor = connection.sql_flavor
        self.flavor_service = get_flavor_service(self.flavor)

    def _get_input_parameters(self, test_def: TestExecutionDef) -> str:
        return "; ".join(
            f"{field.name}={getattr(test_def, field.name)}"
            for field in dataclasses.fields(InputParameters)
            if getattr(test_def, field.name, None) not in [None, ""]
        ).replace("'", "`")

    def _get_params(self, test_def: TestExecutionDef | None = None) -> dict:
        quote = self.flavor_service.quote_character
        params = {
            "TEST_SUITE_ID": self.test_run.test_suite_id,
            "TEST_RUN_ID": self.test_run.id,
            "RUN_DATE": self.run_date,
            "SQL_FLAVOR": self.flavor,
            "VARCHAR_TYPE": self.flavor_service.varchar_type,
            "QUOTE": quote,
        }

        if test_def:
            params.update({
                "TEST_TYPE": test_def.test_type,
                "TEST_DEFINITION_ID": test_def.id,
                "APP_SCHEMA_NAME": get_tg_schema(),
                "SCHEMA_NAME": test_def.schema_name,
                "TABLE_GROUPS_ID": self.table_group.id,
                "TABLE_NAME": test_def.table_name,
                "COLUMN_NAME": f"{quote}{test_def.column_name or ''}{quote}",
                "COLUMN_NAME_NO_QUOTES": test_def.column_name,
                "CONCAT_COLUMNS": concat_columns(test_def.column_name, self.null_value) if test_def.column_name else "",
                "SKIP_ERRORS": test_def.skip_errors or 0,
                "BASELINE_CT": test_def.baseline_ct,
                "BASELINE_UNIQUE_CT": test_def.baseline_unique_ct,
                "BASELINE_VALUE": test_def.baseline_value,
                "BASELINE_VALUE_CT": test_def.baseline_value_ct,
                "THRESHOLD_VALUE": test_def.threshold_value,
                "BASELINE_SUM": test_def.baseline_sum,
                "BASELINE_AVG": test_def.baseline_avg,
                "BASELINE_SD": test_def.baseline_sd,
                "LOWER_TOLERANCE": test_def.lower_tolerance,
                "UPPER_TOLERANCE": test_def.upper_tolerance,
                "SUBSET_CONDITION": test_def.subset_condition or "1=1",
                "GROUPBY_NAMES": test_def.groupby_names,
                "HAVING_CONDITION": f"HAVING {test_def.having_condition}" if test_def.having_condition else "",
                "WINDOW_DATE_COLUMN": test_def.window_date_column,
                "WINDOW_DAYS": test_def.window_days or 0,
                "MATCH_SCHEMA_NAME": test_def.match_schema_name,
                "MATCH_TABLE_NAME": test_def.match_table_name,
                "MATCH_COLUMN_NAMES": test_def.match_column_names,
                "MATCH_SUBSET_CONDITION": test_def.match_subset_condition or "1=1",
                "MATCH_GROUPBY_NAMES": test_def.match_groupby_names,
                "CONCAT_MATCH_GROUPBY": concat_columns(test_def.match_groupby_names, self.null_value) if test_def.match_groupby_names else "",
                "MATCH_HAVING_CONDITION": f"HAVING {test_def.match_having_condition}" if test_def.match_having_condition else "",
                "CUSTOM_QUERY": test_def.custom_query,
                "COLUMN_TYPE": test_def.column_type,
                "INPUT_PARAMETERS": self._get_input_parameters(test_def),
            })
        return params

    def _get_query(
        self,
        template_file_name: str,
        sub_directory: str | None = "execution",
        no_bind: bool = False,
        extra_params: dict | None = None,
        test_def: TestExecutionDef | None = None,
    ) -> tuple[str, dict | None]:
        query = read_template_sql_file(template_file_name, sub_directory)

        params = self._get_params(test_def)
        if extra_params:
            params.update(extra_params)
        query = replace_params(query, params)

        if no_bind:
            query = query.replace(":", "\\:")

        return query, None if no_bind else params

    def get_active_test_definitions(self) -> tuple[dict]:
        # Runs on App database
        return self._get_query("get_active_test_definitions.sql")

    def get_target_identifiers(self, schemas: Iterable[str]) -> tuple[str, dict]:
        # Runs on Target database
        filename = "get_target_identifiers.sql"
        params = {
            "DATA_SCHEMA": self.table_group.table_group_schema,
            "TEST_SCHEMAS": ", ".join([f"'{item}'" for item in schemas]),
        }
        try:
            return self._get_query(filename, f"flavors/{self.connection.sql_flavor}/validate_tests", extra_params=params)
        except ModuleNotFoundError:
            return self._get_query(filename, "flavors/generic/validate_tests", extra_params=params)

    def get_test_errors(self, test_defs: list[TestExecutionDef]) -> list[list[UUID | str | datetime]]:
        return [
            [
                self.test_run.id,
                self.test_run.test_suite_id,
                self.test_run.test_starttime,
                td.id,
                td.test_type,
                td.schema_name,
                td.table_name,
                td.column_name,
                td.skip_errors or 0,
                self._get_input_parameters(td),
                None, # No result_code on errors
                "Error",
                ". ".join(td.errors),
                None, # No result_measure on errors
            ] for td in test_defs if td.errors
        ]

    def disable_invalid_test_definitions(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("disable_invalid_test_definitions.sql")

    def update_historic_thresholds(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("update_historic_thresholds.sql")

    def run_query_test(self, test_def: TestExecutionDef) -> tuple[str, dict]:
        # Runs on Target database
        folder = "generic" if test_def.template_name.endswith("_generic.sql") else self.flavor
        return self._get_query(
            test_def.template_name,
            f"flavors/{folder}/exec_query_tests",
            no_bind=True,
            # Final replace in CUSTOM_QUERY
            extra_params={"DATA_SCHEMA": test_def.schema_name},
            test_def=test_def,
        )

    def aggregate_cat_tests(
        self,
        test_defs: list[TestExecutionDef],
        single: bool = False,
    ) -> tuple[list[tuple[str, None]], list[list[TestExecutionDef]]]:
        varchar_type = self.flavor_service.varchar_type
        concat_operator = self.flavor_service.concat_operator
        quote = self.flavor_service.quote_character

        for td in test_defs:
            # Don't recalculate expressions if it was already done before
            if not td.measure_expression or not td.condition_expression:
                params = self._get_params(td)

                measure = replace_params(td.measure, params)
                measure = replace_templated_functions(measure, self.flavor)
                td.measure_expression = f"COALESCE(CAST({measure} AS {varchar_type}) {concat_operator} '|', '{self.null_value}|')"

                condition = replace_params(f"{td.measure}{td.test_operator}{td.test_condition}", params)
                condition = replace_templated_functions(condition, self.flavor)
                td.condition_expression = f"CASE WHEN {condition} THEN '0,' ELSE '1,' END"

        aggregate_queries: list[tuple[str, None]] = []
        aggregate_test_defs: list[list[TestExecutionDef]] = []

        def add_query(test_defs: list[TestExecutionDef]) -> str:
            if not test_defs:
                return

            query = (
                f"SELECT {len(aggregate_queries)} AS query_index, "
                f"{concat_operator.join([td.measure_expression for td in test_defs])} AS result_measures, "
                f"{concat_operator.join([td.condition_expression for td in test_defs])} AS result_codes "
                f"FROM {quote}{test_defs[0].schema_name}{quote}.{quote}{test_defs[0].table_name}{quote}"
            )
            query = query.replace(":", "\\:")

            aggregate_queries.append((query, None))
            aggregate_test_defs.append(test_defs)

        if single:
            for td in test_defs:
                # Add separate query for each test
                add_query([td])
        else:
            test_defs_by_table: dict[tuple[str, str], list[TestExecutionDef]] = {}
            for td in test_defs:
                table = (td.schema_name, td.table_name)
                if not test_defs_by_table.get(table):
                    test_defs_by_table[table] = []
                test_defs_by_table[table].append(td)

            max_query_chars = self.connection.max_query_chars - 400
            for test_defs in test_defs_by_table.values():
                # Add new query for each table
                current_chars = 0
                current_test_defs = []

                for td in test_defs:
                    td_chars = len(td.measure_expression) + len(td.condition_expression) + 2 * len(concat_operator)
                    # Add new query if current query will become bigger than character limit
                    if (current_chars + td_chars) > max_query_chars:
                        add_query(current_test_defs)
                        current_chars = 0
                        current_test_defs = []

                    current_chars += td_chars
                    current_test_defs.append(td)

                add_query(current_test_defs)

        return aggregate_queries, aggregate_test_defs

    def get_cat_test_results(
        self,
        aggregate_results: list[AggregateResult],
        aggregate_test_defs: list[list[TestExecutionDef]],
    ) -> list[list[UUID | str | datetime | int | None]]:
        test_results: list[list[UUID | str | datetime | int | None]] = []
        for result in aggregate_results:
            test_defs = aggregate_test_defs[result["query_index"]]
            result_measures = result["result_measures"].split("|")
            result_codes = result["result_codes"].split(",")

            for index, td in enumerate(test_defs):
                test_results.append([
                    self.test_run.id,
                    self.test_run.test_suite_id,
                    self.test_run.test_starttime,
                    td.id,
                    td.test_type,
                    td.schema_name,
                    td.table_name,
                    td.column_name,
                    td.skip_errors or 0,
                    self._get_input_parameters(td),
                    result_codes[index],
                    None, # result_status will be calculated later
                    None, # No result_message
                    result_measures[index] if result_measures[index] != self.null_value else None,
                ])

        return test_results

    def update_test_results(self) -> list[tuple[str, dict]]:
        # Runs on App database
        return [
            self._get_query("update_test_results.sql"),
            self._get_query("update_test_run_stats.sql"),
        ]
