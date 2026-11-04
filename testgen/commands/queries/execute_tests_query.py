import dataclasses
import hashlib
from collections.abc import Iterable
from datetime import date, datetime
from typing import ClassVar, TypedDict
from uuid import UUID

import pandas as pd

from testgen.common import read_template_sql_file
from testgen.common.clean_sql import (
    concat_columns,
    expand_subset,
    null_if_empty,
    parse_value_list,
    strip_trailing_semicolons,
    subset_params,
)
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import (
    FinalParam,
    fetch_dict_from_db,
    get_flavor_service,
    get_tg_schema,
    replace_params,
)
from testgen.common.enums import VALUE_LIST_TEST_TYPES, MonitorCalculation, SuiteType, TestScope
from testgen.common.freshness_service import (
    count_excluded_minutes,
    effective_exclude_weekends,
    get_freshness_gated_baseline,
    get_schedule_params,
    is_excluded_day,
    resolve_holiday_dates,
)
from testgen.common.models.connection import DEFAULT_MAX_QUERY_CHARS, Connection
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestRunType
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.common.read_file import replace_templated_functions
from testgen.utils import to_sql_timestamp

# Separates the measures of the CAT tests batched into one aggregate query. parse_cat_results splits
# on it and indexes positionally, so it must be a sequence no measure can contain.
MEASURE_SEPARATOR = "~^~"

# The parameters through which a CAT measure reads the column's value on each record
ROW_LEVEL_PARAMS = ("COLUMN_NAME", "COLUMN_NUM", "COLUMN_VALUE", "VALUE_LIST_COLUMN", "VALUE_LIST_DISTINCT")


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
    custom_query: str

@dataclasses.dataclass
class TestExecutionDef(InputParameters):
    id: UUID
    test_type: str
    schema_name: str
    table_name: str
    column_name: str
    lock_refresh: str
    skip_errors: int
    history_calculation: str
    prediction: dict | str | None
    run_type: TestRunType
    test_scope: TestScope
    template: str
    measure: str
    test_operator: str
    test_condition: str
    null_measure_fails: bool = False
    column_general_types: list[str] | None = None
    # Runtime attributes
    column_type: str = None
    column_chars: ColumnChars | None = None
    key_column_chars: ColumnChars | None = None
    measure_expression: str = None
    condition_expression: str = None
    errors: list[str] = dataclasses.field(default_factory=list)
    # Where this run reads the test's own table. A run-scoped override sets these; otherwise they
    # follow the definition. Kept apart from schema_name and table_name because a result reports
    # those two as its own identity, which stays where the test is defined, and off
    # InputParameters because a result's own location is not what the run read. The match fields
    # carry their override directly, since they are reported as input parameters rather than
    # identity.
    read_schema_name: str | None = None
    read_table_name: str | None = None

    @property
    def source_schema(self) -> str:
        return self.read_schema_name or self.schema_name

    @property
    def source_table(self) -> str:
        return self.read_table_name or self.table_name

    def __post_init__(self) -> None:
        if self.subset_condition is not None and not self.subset_condition.strip():
            self.subset_condition = None

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
    measure_expression = (
        f"COALESCE(CAST({measure} AS {varchar_type}) {concat_operator} '{MEASURE_SEPARATOR}', "
        f"'{null_value}{MEASURE_SEPARATOR}')"
    )

    # For prediction mode, return -1 during training period
    if history_calculation == MonitorCalculation.PREDICT and (
        lower_tolerance in (None, "") or upper_tolerance in (None, "")
    ):
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
    test_time: str,
    input_parameters_fn,
    null_value: str = "<NULL>",
) -> list[list]:
    """Parse aggregate query results into individual test result rows.

    Args:
        aggregate_results: List of aggregate result dicts from DB.
        aggregate_test_defs: List of test def groups matching the queries.
        test_run_id: ID of the current test run.
        test_suite_id: ID of the test suite.
        test_time: The run's label for its result rows, as the query templates interpolate it.
        input_parameters_fn: Callable that takes a TestExecutionDef and returns input params string.
        null_value: Sentinel string for NULL values.

    Returns:
        List of result rows (each row is a list of values).
    """
    test_results: list[list] = []
    for result in aggregate_results:
        test_defs = aggregate_test_defs[result["query_index"]]
        result_measures = result["result_measures"].split(MEASURE_SEPARATOR)
        result_codes = result["result_codes"].split(",")

        for index, td in enumerate(test_defs):
            measure = result_measures[index] if result_measures[index] != null_value else None
            result_code = result_codes[index]
            if measure is None and td.null_measure_fails and result_code == "1":
                result_code = "0"
            test_results.append([
                test_run_id,
                test_suite_id,
                test_time,
                td.id,
                td.test_type,
                td.schema_name,
                td.table_name,
                td.column_name,
                td.skip_errors or 0,
                input_parameters_fn(td),
                result_code,
                None,  # result_status will be calculated later
                None,  # No result_message
                measure,
            ])

    return test_results


def _app_sql_text(value: str | None) -> str:
    """Return ``value`` with its quotes doubled, for a single-quoted application-database literal."""
    return (value or "").replace("'", "''")


def _app_sql_literal(value: str | None) -> str:
    """Return ``value`` as an application-database literal, typed when it is NULL."""
    return "CAST(NULL AS VARCHAR)" if value is None else f"'{_app_sql_text(value)}'"


def _columns_of_table(columns: list[ColumnChars], schema_name: str, table_name: str) -> list[ColumnChars]:
    """Return a table's columns, matched by exact name, else case-insensitively.

    Args:
        columns: The columns read at one location.
        schema_name: The schema the table is read from.
        table_name: The table as the run reads it.

    Returns:
        The columns of that table, in the order they were read.
    """
    exact = [c for c in columns if c.schema_name == schema_name and c.table_name == table_name]
    if exact:
        return exact
    return [
        c
        for c in columns
        if c.schema_name.lower() == schema_name.lower() and c.table_name.lower() == table_name.lower()
    ]


class TestExecutionSQL:

    # The columns of the location this run reads, when it reads somewhere other than the table
    # group. Metadata tests describe the table group's catalog without it.
    run_columns: list[ColumnChars] | None = None

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
    # Columns each run type's test templates select. Stated here rather than read off
    # whichever query returned last, so a template that stops selecting one fails on
    # write instead of shifting the run's results into neighbouring columns.
    template_result_columns: ClassVar[dict[str, tuple[str, ...]]] = {
        "QUERY": (
            "test_type",
            "test_definition_id",
            "test_suite_id",
            "test_run_id",
            "test_time",
            "schema_name",
            "table_name",
            "column_names",
            "threshold_value",
            "skip_errors",
            "input_parameters",
            "result_signal",
            "result_code",
            "result_message",
            "result_measure",
        ),
        "METADATA": (
            "test_type",
            "test_definition_id",
            "test_suite_id",
            "test_run_id",
            "test_time",
            "schema_name",
            "table_name",
            "column_names",
            "input_parameters",
            "result_signal",
            "result_code",
            "result_message",
            "result_measure",
        ),
    }

    def __init__(
        self,
        connection: Connection,
        table_group: TableGroup,
        test_suite: TestSuite,
        test_run: TestRun,
    ):
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
        if test_suite.suite_type == SuiteType.MONITOR:
            schedule = JobSchedule.get(JobSchedule.kwargs["test_suite_id"].astext == str(test_suite.id))
            self._schedule_tz = schedule.cron_tz or "UTC" if schedule else None
            if test_suite.holiday_codes_list:
                self._holiday_dates = resolve_holiday_dates(
                    test_suite.holiday_codes_list,
                    pd.DatetimeIndex([datetime(self.run_date.year - 1, 1, 1), datetime(self.run_date.year + 1, 12, 31)]),
                )
        # Cache of (schema, table) -> "did Freshness_Trend detect a fingerprint change in
        # this run?". True / False / None (no Freshness_Trend result). Populated lazily
        # per table; reused across all Volume/Metric defs for the same table.
        self._freshness_changed_cache: dict[tuple[str, str], bool | None] = {}

    def _freshness_changed_for_table(self, test_def: TestExecutionDef) -> bool | None:
        """Did Freshness_Trend detect a fingerprint change for the test's table in this run?

        Reads the latest Freshness_Trend result_signal written during the current run.
        Freshness_Trend emits `result_signal = '0'` when the table fingerprint differs
        from the previous run's baseline (i.e., an update was detected). Any other value
        (the interval since last update) means no change.

        Returns True / False per the signal, or None if no Freshness_Trend result exists
        for this table in this run.
        """
        cache_key = (test_def.schema_name, test_def.table_name)
        if cache_key in self._freshness_changed_cache:
            return self._freshness_changed_cache[cache_key]

        rows = fetch_dict_from_db(*self._get_query("get_current_freshness_signal.sql", test_def=test_def))
        changed: bool | None = None
        if rows and rows[0].get("result_signal") is not None:
            changed = str(rows[0]["result_signal"]) == "0"
        self._freshness_changed_cache[cache_key] = changed
        return changed

    def _resolve_cat_operator_and_condition(self, test_def: TestExecutionDef) -> tuple[str, str]:
        """Pick the operator / condition pair to feed into build_cat_expressions.

        For Volume_Trend / Metric_Trend with freshness-gating enabled, when Freshness_Trend
        detected no change in this run the table is in a "stale period" — the measure must
        equal baseline_value, and any deviation is a silent-write anomaly. In that case,
        override the test definition's `NOT BETWEEN` band check with a strict equality
        check against baseline_value. All other cases (band check, refresh detected,
        non-monitor test types, or no Freshness_Trend result) keep the test definition's
        own operator and condition.
        """
        if (
            test_def.test_type in ("Volume_Trend", "Metric_Trend")
            and (baseline := get_freshness_gated_baseline(test_def.prediction)) is not None
            and self._freshness_changed_for_table(test_def) is False
        ):
            return "<>", str(baseline)

        return test_def.test_operator, test_def.test_condition

    def _get_input_parameters(self, test_def: TestExecutionDef) -> str:
        # Every value is folded onto one line: this string is templated into a single-quoted SQL
        # literal, and some flavors, BigQuery among them, end such a literal at a line break.
        return "; ".join(
            f"{field.name}={' '.join(str(getattr(test_def, field.name)).split())}"
            for field in dataclasses.fields(InputParameters)
            if getattr(test_def, field.name, None) not in [None, ""]
        ).replace("'", "`")

    def _get_params(self, test_def: TestExecutionDef | None = None) -> dict:
        quote = self.flavor_service.quote_character
        params = {
            "TABLE_GROUPS_ID": self.table_group.id,
            "TEST_SUITE_ID": self.test_run.test_suite_id,
            "VERSION_ID": self.test_run.version_id,
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
                "SCHEMA_NAME": test_def.source_schema,
                "TABLE_NAME": test_def.source_table,
                # The data catalog and a contract's declared schema both describe the table group
                # whatever a run reads, so a template querying either matches on the name the
                # definition carries.
                "CATALOG_TABLE_NAME": test_def.table_name,
                "COLUMN_NAME": f"{quote}{test_def.column_name or ''}{quote}",
                "COLUMN_NAME_NO_QUOTES": test_def.column_name,
                "CONCAT_COLUMNS": concat_columns(test_def.column_name, self.null_value) if test_def.column_name else "",
                "SKIP_ERRORS": test_def.skip_errors or 0,
                "CUSTOM_QUERY": strip_trailing_semicolons(test_def.custom_query),
                # Numeric baseline params feed division/arithmetic in CAT measures.
                # Render empty values as NULL so the measure evaluates to NULL instead of producing
                # invalid SQL like CAST( AS FLOAT). Cannot default to 0 — several are denominators.
                "BASELINE_CT": null_if_empty(test_def.baseline_ct),
                "BASELINE_UNIQUE_CT": null_if_empty(test_def.baseline_unique_ct),
                # BASELINE_VALUE is a quoted literal, an unquoted number, or an IN-list depending on
                # test type — no single empty-substitution is valid SQL, so it is templated as-is.
                "BASELINE_VALUE": test_def.baseline_value,
                "BASELINE_VALUE_CT": null_if_empty(test_def.baseline_value_ct),
                "THRESHOLD_VALUE": test_def.threshold_value or 0,
                # Freshness_Trend uses BASELINE_SUM as a quoted timestamp (the template's
                # NULLIF('{...}', '') handles empty); Other tests use it as a numeric sum.
                "BASELINE_SUM": (
                    test_def.baseline_sum
                    if test_def.test_type == "Freshness_Trend"
                    else null_if_empty(test_def.baseline_sum)
                ),
                "BASELINE_AVG": null_if_empty(test_def.baseline_avg),
                "BASELINE_SD": null_if_empty(test_def.baseline_sd),
                "LOWER_TOLERANCE": null_if_empty(test_def.lower_tolerance),
                "UPPER_TOLERANCE": null_if_empty(test_def.upper_tolerance),
                # SUBSET_CONDITION should be replaced after CUSTOM_QUERY
                # since the latter may contain the former
                "SUBSET_CONDITION": test_def.subset_condition or "1=1",
                **subset_params(test_def.subset_condition),
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
                "COLUMN_VALUE": self.flavor_service.text_value(
                    f"{quote}{test_def.column_name or ''}{quote}",
                    test_def.column_type,
                    test_def.column_chars.db_data_type if test_def.column_chars else None,
                ),
                "COLUMN_NUM": self.flavor_service.numeric_value(
                    f"{quote}{test_def.column_name or ''}{quote}", test_def.column_type
                ),
                "INPUT_PARAMETERS": self._get_input_parameters(test_def),
                # Only the metadata test types read it, and building it for the rest would render
                # a table's whole column list per test.
                "OBSERVED_COLUMNS": (
                    self._observed_columns(test_def) if "{OBSERVED_COLUMNS}" in (test_def.template or "") else ""
                ),
            })

            params.update(self._freshness_exclusion_params(test_def))
            params.update(self.flavor_service.value_hash_params(test_def.column_chars, test_def.key_column_chars))

            # After every user-supplied parameter, since any of them may contain {DATA_SCHEMA}
            params["DATA_SCHEMA"] = test_def.source_schema

            # Substituted last, in one pass, so placeholder text in a listed value is never expanded
            params["BASELINE_VALUE_LIST"] = FinalParam(
                self.flavor_service.string_literal_list(parse_value_list(test_def.baseline_value))
            )
            params["BASELINE_VALUE_LITERAL"] = FinalParam(
                self.flavor_service.string_literal_or_null(test_def.baseline_value)
            )
            if test_def.test_type in VALUE_LIST_TEST_TYPES:
                value_list_params = self.flavor_service.value_list_params(
                    f"{quote}{test_def.column_name or ''}{quote}",
                    test_def.column_chars,
                    parse_value_list(test_def.baseline_value),
                )
                params.update({key: FinalParam(value) for key, value in value_list_params.items()})

        return params

    def _observed_columns(self, test_def: TestExecutionDef) -> str:
        """Return the derived table a metadata test reads a table's observed columns from.

        Args:
            test_def: The test being executed.

        Returns:
            A ``FROM`` item aliased ``oc``, holding ``column_name``, ``general_type``,
            ``db_data_type``, and ``logical_type``. It selects the data catalog's record of the
            table group's table, or, for a run reading another location, the columns read there.
        """
        if self.run_columns is None:
            return (
                "(SELECT column_name, general_type, db_data_type, logical_type"
                f" FROM {get_tg_schema()}.data_column_chars"
                f" WHERE table_groups_id = '{self.table_group.id}'"
                f" AND table_name = '{_app_sql_text(test_def.table_name)}'"
                " AND drop_date IS NULL) oc"
            )

        columns = _columns_of_table(self.run_columns, test_def.source_schema, test_def.source_table)
        if not columns:
            # VALUES needs a row. A table the run does not hold has none, and the tests read it
            # as the catalog reads a table it has no record of.
            return (
                "(SELECT CAST(NULL AS VARCHAR) AS column_name, CAST(NULL AS VARCHAR) AS general_type,"
                " CAST(NULL AS VARCHAR) AS db_data_type, CAST(NULL AS VARCHAR) AS logical_type"
                " WHERE FALSE) oc"
            )

        rows = ", ".join(
            f"({_app_sql_literal(column.column_name)}, {_app_sql_literal(column.general_type)}, {_app_sql_literal(column.db_data_type)}, {_app_sql_literal(column.logical_type)})"
            for column in columns
        )
        return f"(VALUES {rows}) oc(column_name, general_type, db_data_type, logical_type)"

    def _freshness_exclusion_params(self, test_def: TestExecutionDef) -> dict:
        """Freshness exclusion parameters for a test at this run's date.

        :param test_def: The test definition being executed.
        :returns: ``EXCLUDED_MINUTES`` between the last detected update and the run date, and
            ``IS_EXCLUDED_DAY`` (1 or 0) for the run date; both 0 for other test types, when
            no update has been detected, or when nothing is excluded.
        """
        no_exclusions = {"EXCLUDED_MINUTES": 0, "IS_EXCLUDED_DAY": 0}
        if test_def.test_type != "Freshness_Trend" or not test_def.baseline_sum:
            return no_exclusions

        sched = get_schedule_params(test_def.prediction)
        exclude_weekends = effective_exclude_weekends(self._exclude_weekends, sched.excluded_days)
        if not (exclude_weekends or self._holiday_dates or sched.excluded_days or sched.window_start is not None):
            return no_exclusions

        exclusions = {
            "exclude_weekends": exclude_weekends,
            "holiday_dates": self._holiday_dates,
            "tz": self._schedule_tz,
            "excluded_days": sched.excluded_days,
            "window_start": sched.window_start,
            "window_end": sched.window_end,
        }
        run_date = pd.Timestamp(self.run_date)
        return {
            "EXCLUDED_MINUTES": round(count_excluded_minutes(pd.Timestamp(test_def.baseline_sum), run_date, **exclusions)),
            "IS_EXCLUDED_DAY": 1 if is_excluded_day(run_date, **exclusions) else 0,
        }

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

    def get_target_identifiers(self, schema: str) -> tuple[str, dict]:
        # Runs on Target database
        filename = "get_target_identifiers.sql"
        params = {
            # Both name the one schema being read. A flavor whose information schema is scoped to
            # a single schema, such as BigQuery, introspects DATA_SCHEMA and would find nothing
            # for a TEST_SCHEMAS naming any other.
            "DATA_SCHEMA": schema,
            "TEST_SCHEMAS": f"'{schema}'",
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
                to_sql_timestamp(self.run_date),
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

    def run_query_test(self, test_def: TestExecutionDef) -> tuple[str, dict | None]:
        # Runs on Target database
        if test_def.template.startswith("@"):
            folder = "generic" if test_def.template.endswith("_generic.sql") else self.flavor
            return self._get_query(
                test_def.template,
                f"flavors/{folder}/exec_query_tests",
                no_bind=True,
                test_def=test_def,
            )
        else:
            query = replace_params(test_def.template, self._get_params(test_def))
            # Unbound, like the CAT queries: a substituted value may contain a colon
            return query.replace(":", "\\:"), None

    def aggregate_cat_tests(
        self,
        test_defs: list[TestExecutionDef],
        single: bool = False,
    ) -> tuple[list[tuple[str, None]], list[list[TestExecutionDef]]]:
        varchar_type = self.flavor_service.varchar_type
        concat_operator = self.flavor_service.concat_operator

        for td in test_defs:
            # Don't recalculate expressions if it was already done before
            if not td.measure_expression or not td.condition_expression:
                params = self._get_params(td)
                operator, condition_template = self._resolve_cat_operator_and_condition(td)

                # Records outside the subset read as NULL, which the measure's aggregates skip,
                # so subset and whole-table tests still share one scan of the table.
                measure_params = params
                if td.subset_condition:
                    flag = self._subset_flag(td)
                    in_subset = f"{flag} = 1"
                    measure_params = {**params, "SUBSET_CONDITION": in_subset, "SUBSET_ROW": flag}
                    for name in ROW_LEVEL_PARAMS:
                        if name in params:
                            wrapped = f"(CASE WHEN {in_subset} THEN {params[name]} END)"
                            measure_params[name] = FinalParam(wrapped) if isinstance(params[name], FinalParam) else wrapped

                measure = replace_params(td.measure, measure_params)
                measure = replace_templated_functions(measure, self.flavor)
                condition = replace_params(condition_template, params)
                condition = replace_templated_functions(condition, self.flavor)

                td.measure_expression, td.condition_expression = build_cat_expressions(
                    measure=measure,
                    test_operator=operator,
                    test_condition=condition,
                    history_calculation=td.history_calculation,
                    lower_tolerance=td.lower_tolerance,
                    upper_tolerance=td.upper_tolerance,
                    varchar_type=varchar_type,
                    concat_operator=concat_operator,
                    null_value=self.null_value,
                )

        # Every subset of a table is evaluated once per record in the FROM clause; reserve room for all of them
        subset_columns_by_table: dict[tuple[str, str], dict[str, None]] = {}
        for td in test_defs:
            if td.subset_condition:
                subset_columns_by_table.setdefault((td.source_schema, td.source_table), {})[self._subset_column(td)] = None
        max_query_chars = (self.connection.max_query_chars or DEFAULT_MAX_QUERY_CHARS) - 400
        max_query_chars -= max(
            (len(self._from_clause(schema, table, columns)) for (schema, table), columns in subset_columns_by_table.items()),
            default=0,
        )
        groups = group_cat_tests(test_defs, max_query_chars, concat_operator, single)

        aggregate_queries: list[tuple[str, None]] = []
        aggregate_test_defs: list[list[TestExecutionDef]] = []
        for group in groups:
            # Grouped by the definition's table, so every member of a group reads the same one.
            subset_columns = dict.fromkeys(self._subset_column(td) for td in group if td.subset_condition)
            table_ref = self._from_clause(group[0].source_schema, group[0].source_table, subset_columns)
            query = (
                f"SELECT {len(aggregate_queries)} AS query_index, "
                f"{concat_operator.join([td.measure_expression for td in group])} AS result_measures, "
                f"{concat_operator.join([td.condition_expression for td in group])} AS result_codes "
                f"FROM {table_ref}"
            )
            query = query.replace(":", "\\:")

            aggregate_queries.append((query, None))
            aggregate_test_defs.append(group)

        return aggregate_queries, aggregate_test_defs

    def _from_clause(self, schema_name: str, table_name: str, subset_columns: Iterable[str]) -> str:
        """Return the FROM target of an aggregate query: the table, or a derived table adding ``subset_columns``."""
        table_ref = self.flavor_service.get_table_ref(schema_name, table_name, self.connection.sql_flavor_code)
        if not (columns := "".join(subset_columns)):
            return table_ref
        # Aliased by the table's own name, so a subset naming the table still resolves
        alias = f"{self.flavor_service.quote_character}{table_name}{self.flavor_service.quote_character}"
        return f"(SELECT {alias}.*{columns} FROM {table_ref} {alias}) {alias}"

    def _subset_flag(self, test_def: TestExecutionDef) -> str:
        """Return the quoted column that is 1 on the records in ``test_def``'s subset and NULL on the others.

        Tests with the same subset condition on a table share the column.
        """
        digest = hashlib.md5(self._expanded_subset(test_def).encode(), usedforsecurity=False).hexdigest()[:12]
        quote = self.flavor_service.quote_character
        return f"{quote}tg_subset_{digest}{quote}"

    def _subset_column(self, test_def: TestExecutionDef) -> str:
        """Return the select-list entry that computes ``test_def``'s subset flag column, with a leading comma."""
        return f", CASE WHEN ({self._expanded_subset(test_def)}) THEN 1 END AS {self._subset_flag(test_def)}"

    def _expanded_subset(self, test_def: TestExecutionDef) -> str:
        # Written into the query directly, so no later parameter pass expands DATA_SCHEMA in it
        return expand_subset(test_def.subset_condition, test_def.source_schema)

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
            test_time=to_sql_timestamp(self.run_date),
            input_parameters_fn=self._get_input_parameters,
            null_value=self.null_value,
        )

    def update_test_results(self) -> list[tuple[str, dict]]:
        # Runs on App database
        return [
            self._get_query("update_test_results.sql"),
            self._get_query("update_test_run_stats.sql"),
        ]
