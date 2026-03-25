import dataclasses
from collections.abc import Iterable
from datetime import date, datetime
from typing import TypedDict
from uuid import UUID

import pandas as pd

from testgen.common import read_template_sql_file
from testgen.common.clean_sql import concat_columns
from testgen.common.database.database_service import get_flavor_service, get_tg_schema, replace_params
from testgen.common.freshness_service import (
    count_excluded_minutes,
    get_schedule_params,
    is_excluded_day,
    resolve_holiday_dates,
)
from testgen.common.models.connection import Connection
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestRunType, TestScope
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.common.read_file import replace_templated_functions
from testgen.utils import to_sql_timestamp


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
    history_calculation: str
    custom_query: str
    prediction: dict | str | None
    run_type: TestRunType
    test_scope: TestScope
    template: str
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


def build_cat_expressions(
    measure: str,
    test_operator: str,
    test_condition: str,
    history_calculation: str,
    lower_tolerance: str,
    upper_tolerance: str,
    varchar_type: str,
    concat_operator: str,
    null_value: str = "<NULL>",
) -> tuple[str, str]:
    """Build measure_expression and condition_expression for a CAT test.

    Args:
        measure: Already-resolved measure SQL expression.
        test_operator: Comparison operator (e.g., "=", "BETWEEN").
        test_condition: Already-resolved test condition SQL expression.
        history_calculation: "PREDICT" for prediction mode, anything else for normal.
        lower_tolerance: Lower tolerance value (empty/None means training mode for PREDICT).
        upper_tolerance: Upper tolerance value (empty/None means training mode for PREDICT).
        varchar_type: DB-specific varchar type (e.g., "VARCHAR", "STRING").
        concat_operator: DB-specific concat operator (e.g., "||", "+").
        null_value: Sentinel string for NULL values.

    Returns:
        (measure_expression, condition_expression)
    """
    measure_expression = f"COALESCE(CAST({measure} AS {varchar_type}) {concat_operator} '|', '{null_value}|')"

    # For prediction mode, return -1 during training period
    if history_calculation == "PREDICT" and (lower_tolerance in (None, "") or upper_tolerance in (None, "")):
        condition_expression = "'-1,'"
    else:
        condition = (
            f"{measure} {test_operator} {test_condition}"
            if "BETWEEN" in test_operator
            else f"{measure}{test_operator}{test_condition}"
        )
        condition_expression = f"CASE WHEN {condition} THEN '0,' ELSE '1,' END"

    return measure_expression, condition_expression


def group_cat_tests(
    test_defs: list[TestExecutionDef],
    max_query_chars: int,
    concat_operator: str,
    single: bool = False,
) -> list[list[TestExecutionDef]]:
    """Group test defs into batches respecting character limit.

    All test defs must have measure_expression and condition_expression set.

    Args:
        test_defs: List of test defs with expressions already set.
        max_query_chars: Maximum characters per query.
        concat_operator: DB-specific concat operator for calculating expression size.
        single: If True, put each test def in its own group.

    Returns:
        List of groups, where each group is a list of test defs.
    """
    if single:
        return [[td] for td in test_defs]

    test_defs_by_table: dict[tuple[str, str], list[TestExecutionDef]] = {}
    for td in test_defs:
        table = (td.schema_name, td.table_name)
        if not test_defs_by_table.get(table):
            test_defs_by_table[table] = []
        test_defs_by_table[table].append(td)

    groups: list[list[TestExecutionDef]] = []
    for table_test_defs in test_defs_by_table.values():
        current_chars = 0
        current_group: list[TestExecutionDef] = []

        for td in table_test_defs:
            td_chars = len(td.measure_expression) + len(td.condition_expression) + 2 * len(concat_operator)
            if (current_chars + td_chars) > max_query_chars:
                if current_group:
                    groups.append(current_group)
                current_chars = 0
                current_group = []

            current_chars += td_chars
            current_group.append(td)

        if current_group:
            groups.append(current_group)

    return groups


def parse_cat_results(
    aggregate_results: list[AggregateResult],
    aggregate_test_defs: list[list[TestExecutionDef]],
    test_run_id: UUID,
    test_suite_id: UUID | str,
    test_starttime: datetime,
    input_parameters_fn,
    null_value: str = "<NULL>",
) -> list[list]:
    """Parse aggregate query results into individual test result rows.

    Args:
        aggregate_results: List of aggregate result dicts from DB.
        aggregate_test_defs: List of test def groups matching the queries.
        test_run_id: ID of the current test run.
        test_suite_id: ID of the test suite.
        test_starttime: Start time of the test run.
        input_parameters_fn: Callable that takes a TestExecutionDef and returns input params string.
        null_value: Sentinel string for NULL values.

    Returns:
        List of result rows (each row is a list of values).
    """
    test_results: list[list] = []
    for result in aggregate_results:
        test_defs = aggregate_test_defs[result["query_index"]]
        result_measures = result["result_measures"].split("|")
        result_codes = result["result_codes"].split(",")

        for index, td in enumerate(test_defs):
            test_results.append([
                test_run_id,
                test_suite_id,
                test_starttime,
                td.id,
                td.test_type,
                td.schema_name,
                td.table_name,
                td.column_name,
                td.skip_errors or 0,
                input_parameters_fn(td),
                result_codes[index],
                None,  # result_status will be calculated later
                None,  # No result_message
                result_measures[index] if result_measures[index] != null_value else None,
            ])

    return test_results


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

    def __init__(self, connection: Connection, table_group: TableGroup, test_suite: TestSuite, test_run: TestRun):
        self.connection = connection
        self.table_group = table_group
        self.test_suite = test_suite
        self.test_run = test_run
        self.run_date = test_run.test_starttime
        self.flavor = connection.sql_flavor
        self.flavor_service = get_flavor_service(self.flavor)

        self._exclude_weekends = bool(self.test_suite.predict_exclude_weekends)
        self._holiday_dates: set[date] | None = None
        self._schedule_tz: str | None = None
        if test_suite.is_monitor:
            schedule = JobSchedule.get(JobSchedule.kwargs["test_suite_id"].astext == str(test_suite.id))
            self._schedule_tz = schedule.cron_tz or "UTC" if schedule else None
            if test_suite.holiday_codes_list:
                self._holiday_dates = resolve_holiday_dates(
                    test_suite.holiday_codes_list,
                    pd.DatetimeIndex([datetime(self.run_date.year - 1, 1, 1), datetime(self.run_date.year + 1, 12, 31)]),
                )

    def _get_input_parameters(self, test_def: TestExecutionDef) -> str:
        return "; ".join(
            f"{field.name}={getattr(test_def, field.name)}"
            for field in dataclasses.fields(InputParameters)
            if getattr(test_def, field.name, None) not in [None, ""]
        ).replace("'", "`")

    def _get_params(self, test_def: TestExecutionDef | None = None) -> dict:
        quote = self.flavor_service.quote_character
        params = {
            "TABLE_GROUPS_ID": self.table_group.id,
            "TEST_SUITE_ID": self.test_run.test_suite_id,
            "TEST_RUN_ID": self.test_run.id,
            "RUN_DATE": to_sql_timestamp(self.run_date),
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
                "TABLE_NAME": test_def.table_name,
                "COLUMN_NAME": f"{quote}{test_def.column_name or ''}{quote}",
                "COLUMN_NAME_NO_QUOTES": test_def.column_name,
                "CONCAT_COLUMNS": concat_columns(test_def.column_name, self.null_value) if test_def.column_name else "",
                "SKIP_ERRORS": test_def.skip_errors or 0,
                "CUSTOM_QUERY": test_def.custom_query,
                "BASELINE_CT": test_def.baseline_ct,
                "BASELINE_UNIQUE_CT": test_def.baseline_unique_ct,
                "BASELINE_VALUE": test_def.baseline_value,
                "BASELINE_VALUE_CT": test_def.baseline_value_ct,
                "THRESHOLD_VALUE": test_def.threshold_value or 0,
                "BASELINE_SUM": test_def.baseline_sum,
                "BASELINE_AVG": test_def.baseline_avg,
                "BASELINE_SD": test_def.baseline_sd,
                "LOWER_TOLERANCE": "NULL" if test_def.lower_tolerance in (None, "") else test_def.lower_tolerance,
                "UPPER_TOLERANCE": "NULL" if test_def.upper_tolerance in (None, "") else test_def.upper_tolerance,
                # SUBSET_CONDITION should be replaced after CUSTOM_QUERY
                # since the latter may contain the former
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
                "COLUMN_TYPE": test_def.column_type,
                "INPUT_PARAMETERS": self._get_input_parameters(test_def),
            })

            # Freshness exclusion params — computed per test at execution time
            if test_def.test_type == "Freshness_Trend" and test_def.baseline_sum:
                sched = get_schedule_params(test_def.prediction)
                # Once the schedule is active (excluded_days derived from active_days),
                # it supersedes exclude_weekends as the single source of truth for
                # day exclusion — avoids conflicts where a detection day (e.g. Saturday)
                # is active per schedule but excluded per exclude_weekends.
                effective_exclude_weekends = False if sched.excluded_days else self._exclude_weekends
                has_exclusions = effective_exclude_weekends or sched.excluded_days or sched.window_start is not None
                if has_exclusions:
                    last_update = pd.Timestamp(test_def.baseline_sum)
                    excluded = round(count_excluded_minutes(
                        last_update, self.run_date, effective_exclude_weekends, self._holiday_dates,
                        tz=self._schedule_tz, excluded_days=sched.excluded_days,
                        window_start=sched.window_start, window_end=sched.window_end,
                    ))
                    is_excl = 1 if is_excluded_day(
                        pd.Timestamp(self.run_date), effective_exclude_weekends, self._holiday_dates,
                        tz=self._schedule_tz, excluded_days=sched.excluded_days,
                        window_start=sched.window_start, window_end=sched.window_end,
                    ) else 0
                    params["EXCLUDED_MINUTES"] = excluded
                    params["IS_EXCLUDED_DAY"] = is_excl
                else:
                    params["EXCLUDED_MINUTES"] = 0
                    params["IS_EXCLUDED_DAY"] = 0
            else:
                params["EXCLUDED_MINUTES"] = 0
                params["IS_EXCLUDED_DAY"] = 0

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

    def has_schema_changes(self) -> tuple[dict]:
        # Runs on App database
        return self._get_query("has_schema_changes.sql")

    def get_missing_freshness_monitors(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("get_missing_freshness_monitors.sql")

    def get_errored_autogen_monitors(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("get_errored_autogen_monitors.sql")

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

    def update_history_calc_thresholds(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("update_history_calc_thresholds.sql")

    def run_query_test(self, test_def: TestExecutionDef) -> tuple[str, dict]:
        # Runs on Target database
        if test_def.template.startswith("@"):
            folder = "generic" if test_def.template.endswith("_generic.sql") else self.flavor
            return self._get_query(
                test_def.template,
                f"flavors/{folder}/exec_query_tests",
                no_bind=True,
                # Final replace in CUSTOM_QUERY
                extra_params={"DATA_SCHEMA": test_def.schema_name},
                test_def=test_def,
            )
        else:
            query = test_def.template
            params = self._get_params(test_def)
            params.update({"DATA_SCHEMA": test_def.schema_name})
            query = replace_params(query, params)
            return query, params

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
                condition = replace_params(td.test_condition, params)
                condition = replace_templated_functions(condition, self.flavor)

                td.measure_expression, td.condition_expression = build_cat_expressions(
                    measure=measure,
                    test_operator=td.test_operator,
                    test_condition=condition,
                    history_calculation=td.history_calculation,
                    lower_tolerance=td.lower_tolerance,
                    upper_tolerance=td.upper_tolerance,
                    varchar_type=varchar_type,
                    concat_operator=concat_operator,
                    null_value=self.null_value,
                )

        max_query_chars = self.connection.max_query_chars - 400
        groups = group_cat_tests(test_defs, max_query_chars, concat_operator, single)

        aggregate_queries: list[tuple[str, None]] = []
        aggregate_test_defs: list[list[TestExecutionDef]] = []
        for group in groups:
            query = (
                f"SELECT {len(aggregate_queries)} AS query_index, "
                f"{concat_operator.join([td.measure_expression for td in group])} AS result_measures, "
                f"{concat_operator.join([td.condition_expression for td in group])} AS result_codes "
                f"FROM {quote}{group[0].schema_name}{quote}.{quote}{group[0].table_name}{quote}"
            )
            query = query.replace(":", "\\:")

            aggregate_queries.append((query, None))
            aggregate_test_defs.append(group)

        return aggregate_queries, aggregate_test_defs

    def get_cat_test_results(
        self,
        aggregate_results: list[AggregateResult],
        aggregate_test_defs: list[list[TestExecutionDef]],
    ) -> list[list[UUID | str | datetime | int | None]]:
        return parse_cat_results(
            aggregate_results=aggregate_results,
            aggregate_test_defs=aggregate_test_defs,
            test_run_id=self.test_run.id,
            test_suite_id=self.test_run.test_suite_id,
            test_starttime=self.test_run.test_starttime,
            input_parameters_fn=self._get_input_parameters,
            null_value=self.null_value,
        )

    def update_test_results(self) -> list[tuple[str, dict]]:
        # Runs on App database
        return [
            self._get_query("update_test_results.sql"),
            self._get_query("update_test_run_stats.sql"),
        ]
