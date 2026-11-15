from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands.queries.execute_tests_query import (
    MEASURE_SEPARATOR,
    TestExecutionDef,
    TestExecutionSQL,
    build_cat_expressions,
    group_cat_tests,
    parse_cat_results,
)
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import get_flavor_service, replace_params
from testgen.common.enums import SuiteType
from testgen.common.models.connection import Connection

pytestmark = pytest.mark.unit


def _make_td(**overrides) -> TestExecutionDef:
    """Build a minimal TestExecutionDef with sensible defaults."""
    defaults = {
        "id": uuid4(),
        "test_type": "Alpha",
        "schema_name": "public",
        "table_name": "orders",
        "column_name": "amount",
        "lock_refresh": "N",
        "skip_errors": 0,
        "history_calculation": "NONE",
        "custom_query": "",
        "default_parm_columns": "",
        "prediction": None,
        "run_type": "CAT",
        "test_scope": "column",
        "template": "",
        "measure": "COUNT(*)",
        "test_operator": ">=",
        "test_condition": "100",
        "baseline_ct": "",
        "baseline_unique_ct": "",
        "baseline_value": "",
        "baseline_value_ct": "",
        "threshold_value": "",
        "baseline_sum": "",
        "baseline_avg": "",
        "baseline_sd": "",
        "lower_tolerance": "",
        "upper_tolerance": "",
        "subset_condition": "",
        "groupby_names": "",
        "having_condition": "",
        "window_date_column": "",
        "window_days": "",
        "match_schema_name": "",
        "match_table_name": "",
        "match_column_names": "",
        "match_subset_condition": "",
        "match_groupby_names": "",
        "match_having_condition": "",
    }
    defaults.update(overrides)
    return TestExecutionDef(**defaults)


def _make_input_params_fn():
    return lambda td: f"params_for_{td.test_type}"


# --- build_cat_expressions ---


def test_build_basic_measure_with_coalesce_cast():
    measure_expr, _ = build_cat_expressions(
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        history_calculation="NONE",
        lower_tolerance="10",
        upper_tolerance="200",
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    assert "COALESCE(CAST(COUNT(*) AS VARCHAR)" in measure_expr
    assert "||" in measure_expr
    assert f"'{MEASURE_SEPARATOR}'" in measure_expr
    assert f"<NULL>{MEASURE_SEPARATOR}" in measure_expr


def test_build_normal_pass_fail_condition():
    _, cond_expr = build_cat_expressions(
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        history_calculation="NONE",
        lower_tolerance="10",
        upper_tolerance="200",
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    assert "CASE WHEN" in cond_expr
    assert "COUNT(*)>=100" in cond_expr
    assert "THEN '0,'" in cond_expr
    assert "ELSE '1,'" in cond_expr


def test_build_between_operator_spacing():
    _, cond_expr = build_cat_expressions(
        measure="AVG(price)",
        test_operator=" BETWEEN ",
        test_condition="10 AND 200",
        history_calculation="NONE",
        lower_tolerance="10",
        upper_tolerance="200",
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    # BETWEEN branch uses f"{measure} {operator} {condition}" — double spaces expected
    # since operator already includes spaces
    assert "AVG(price)  BETWEEN  10 AND 200" in cond_expr


def test_build_non_between_operator_no_spacing():
    _, cond_expr = build_cat_expressions(
        measure="COUNT(*)",
        test_operator="<=",
        test_condition="500",
        history_calculation="NONE",
        lower_tolerance="10",
        upper_tolerance="200",
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    assert "COUNT(*)<=500" in cond_expr


def test_build_prediction_mode_training():
    """PREDICT mode without tolerances should return -1 (training)."""
    _, cond_expr = build_cat_expressions(
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        history_calculation="PREDICT",
        lower_tolerance="",
        upper_tolerance="",
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    assert cond_expr == "'-1,'"


def test_build_prediction_mode_with_tolerances():
    """PREDICT mode with tolerances should produce normal condition."""
    _, cond_expr = build_cat_expressions(
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        history_calculation="PREDICT",
        lower_tolerance="50",
        upper_tolerance="200",
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    assert "CASE WHEN" in cond_expr


def test_build_prediction_partial_tolerance_is_training():
    """PREDICT with only lower tolerance set should still be training mode."""
    _, cond_expr = build_cat_expressions(
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        history_calculation="PREDICT",
        lower_tolerance="50",
        upper_tolerance="",
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    assert cond_expr == "'-1,'"


def test_build_prediction_zero_tolerance_is_not_training():
    """PREDICT with tolerance of 0 should produce normal condition, not training mode."""
    _, cond_expr = build_cat_expressions(
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        history_calculation="PREDICT",
        lower_tolerance=0,
        upper_tolerance=0,
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    assert "CASE WHEN" in cond_expr


def test_build_prediction_zero_lower_tolerance_is_not_training():
    """PREDICT with lower_tolerance=0 and a valid upper should produce normal condition."""
    _, cond_expr = build_cat_expressions(
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        history_calculation="PREDICT",
        lower_tolerance=0,
        upper_tolerance="200",
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    assert "CASE WHEN" in cond_expr


def test_build_prediction_none_tolerance_is_training():
    """PREDICT with None tolerances should return training mode."""
    _, cond_expr = build_cat_expressions(
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        history_calculation="PREDICT",
        lower_tolerance=None,
        upper_tolerance=None,
        varchar_type="VARCHAR",
        concat_operator="||",
    )
    assert cond_expr == "'-1,'"


def test_build_custom_null_value():
    measure_expr, _ = build_cat_expressions(
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        history_calculation="NONE",
        lower_tolerance="",
        upper_tolerance="",
        varchar_type="VARCHAR",
        concat_operator="||",
        null_value="MISSING",
    )
    assert f"'MISSING{MEASURE_SEPARATOR}'" in measure_expr


def test_measure_separator_cannot_appear_in_a_measure():
    """LOV_All aggregates column values with '|', so '|' cannot separate measures."""
    assert "|" not in MEASURE_SEPARATOR
    assert ":" not in MEASURE_SEPARATOR  # aggregate_cat_tests escapes ':' as a bind marker
    assert "," not in MEASURE_SEPARATOR  # result_codes separator


# --- group_cat_tests ---


def test_group_single_mode():
    tds = [_make_td(measure_expression="m1", condition_expression="c1"),
           _make_td(measure_expression="m2", condition_expression="c2")]
    groups = group_cat_tests(tds, max_query_chars=10000, concat_operator="||", single=True)
    assert len(groups) == 2
    assert len(groups[0]) == 1
    assert len(groups[1]) == 1


def test_group_all_fit_in_one():
    tds = [_make_td(measure_expression="m1", condition_expression="c1"),
           _make_td(measure_expression="m2", condition_expression="c2")]
    groups = group_cat_tests(tds, max_query_chars=10000, concat_operator="||")
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_group_character_overflow_splits():
    # Each td takes len("m"*50) + len("c"*50) + 2*len("||") = 104 chars
    tds = [_make_td(measure_expression="m" * 50, condition_expression="c" * 50) for _ in range(3)]
    # max_query_chars = 250 fits 2 tds (208 <= 250), third overflows (312 > 250)
    groups = group_cat_tests(tds, max_query_chars=250, concat_operator="||")
    assert len(groups) == 2
    assert len(groups[0]) == 2
    assert len(groups[1]) == 1


def test_group_different_tables_separate():
    td1 = _make_td(schema_name="public", table_name="orders",
                    measure_expression="m1", condition_expression="c1")
    td2 = _make_td(schema_name="public", table_name="customers",
                    measure_expression="m2", condition_expression="c2")
    groups = group_cat_tests([td1, td2], max_query_chars=10000, concat_operator="||")
    assert len(groups) == 2


def test_group_empty_input():
    groups = group_cat_tests([], max_query_chars=10000, concat_operator="||")
    assert groups == []


def test_group_same_table_together():
    tds = [_make_td(schema_name="s", table_name="t",
                     measure_expression="m", condition_expression="c") for _ in range(5)]
    groups = group_cat_tests(tds, max_query_chars=10000, concat_operator="||")
    assert len(groups) == 1
    assert len(groups[0]) == 5


# --- parse_cat_results ---


def test_parse_basic_single_result():
    td = _make_td(test_type="Alpha")
    test_defs = [[td]]
    results = [{"query_index": 0, "result_measures": f"42{MEASURE_SEPARATOR}", "result_codes": "1,"}]
    run_id = uuid4()
    suite_id = uuid4()
    run_date = "2026-01-01 00:00:00"

    rows = parse_cat_results(results, test_defs, run_id, suite_id, run_date,
                              _make_input_params_fn())
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == run_id
    assert row[1] == suite_id
    assert row[2] == run_date
    assert row[3] == td.id
    assert row[10] == "1"  # result_code
    assert row[13] == "42"  # result_measure


def test_parse_null_value_handling():
    td = _make_td()
    test_defs = [[td]]
    results = [{"query_index": 0, "result_measures": f"<NULL>{MEASURE_SEPARATOR}", "result_codes": "0,"}]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              "2026-01-01 00:00:00", _make_input_params_fn())
    assert rows[0][13] is None  # <NULL> should become None


@pytest.mark.parametrize(
    ("null_measure_fails", "measure", "code", "expected"),
    [
        (True, "<NULL>", "1", "0"),
        (True, "<NULL>", "-1", "-1"),
        (True, "5", "1", "1"),
        (False, "<NULL>", "1", "1"),
    ],
)
def test_parse_null_measure_fails_only_for_flagged_types(null_measure_fails, measure, code, expected):
    td = _make_td(null_measure_fails=null_measure_fails)
    results = [{"query_index": 0, "result_measures": f"{measure}{MEASURE_SEPARATOR}", "result_codes": f"{code},"}]

    rows = parse_cat_results(results, [[td]], uuid4(), uuid4(), "2026-01-01 00:00:00", _make_input_params_fn())

    assert rows[0][10] == expected


def test_parse_multi_test_per_query():
    td1 = _make_td(test_type="Alpha")
    td2 = _make_td(test_type="Beta")
    test_defs = [[td1, td2]]
    results = [{
        "query_index": 0,
        "result_measures": f"10{MEASURE_SEPARATOR}20{MEASURE_SEPARATOR}",
        "result_codes": "1,0,",
    }]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              "2026-01-01 00:00:00", _make_input_params_fn())
    assert len(rows) == 2
    assert rows[0][13] == "10"
    assert rows[1][13] == "20"
    assert rows[0][10] == "1"
    assert rows[1][10] == "0"


def test_parse_measure_containing_pipes_does_not_shift_later_tests():
    """LOV_All's measure is a pipe-joined list; it must not consume later tests' positions."""
    lov = _make_td(test_type="LOV_All")
    row_ct = _make_td(test_type="Row_Ct")
    constant = _make_td(test_type="Constant")
    test_defs = [[lov, row_ct, constant]]
    results = [{
        "query_index": 0,
        "result_measures": MEASURE_SEPARATOR.join(["No|Yes", "47707", "23451", ""]),
        "result_codes": "1,1,0,",
    }]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              datetime.now(UTC), _make_input_params_fn())
    assert [row[13] for row in rows] == ["No|Yes", "47707", "23451"]


def test_parse_multiple_queries():
    td1 = _make_td(test_type="Alpha")
    td2 = _make_td(test_type="Beta")
    test_defs = [[td1], [td2]]
    results = [
        {"query_index": 0, "result_measures": f"10{MEASURE_SEPARATOR}", "result_codes": "1,"},
        {"query_index": 1, "result_measures": f"20{MEASURE_SEPARATOR}", "result_codes": "0,"},
    ]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              "2026-01-01 00:00:00", _make_input_params_fn())
    assert len(rows) == 2
    assert rows[0][4] == "Alpha"
    assert rows[1][4] == "Beta"


def test_parse_result_code_negative_one():
    """Training mode result (-1) should pass through."""
    td = _make_td()
    test_defs = [[td]]
    results = [{"query_index": 0, "result_measures": f"42{MEASURE_SEPARATOR}", "result_codes": "-1,"}]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              "2026-01-01 00:00:00", _make_input_params_fn())
    assert rows[0][10] == "-1"


# --- TestExecutionSQL freshness-gating helpers ---


def _make_execution_sql() -> TestExecutionSQL:
    """Build a minimal TestExecutionSQL instance for testing instance methods.

    Bypasses __init__ (which hits the database) and sets only the attributes the
    freshness-gating methods touch.
    """
    instance = TestExecutionSQL.__new__(TestExecutionSQL)
    instance._freshness_changed_cache = {}
    return instance


FRESHNESS_FETCH_TARGET = "testgen.commands.queries.execute_tests_query.fetch_dict_from_db"


@patch.object(TestExecutionSQL, "_get_query", return_value=("SELECT ...", {}))
@patch(FRESHNESS_FETCH_TARGET)
def test_freshness_changed_true_when_result_signal_is_zero(mock_fetch, _mock_query):
    mock_fetch.return_value = [{"result_signal": "0"}]
    instance = _make_execution_sql()
    assert instance._freshness_changed_for_table(_make_td()) is True


@patch.object(TestExecutionSQL, "_get_query", return_value=("SELECT ...", {}))
@patch(FRESHNESS_FETCH_TARGET)
def test_freshness_changed_false_when_result_signal_is_interval(mock_fetch, _mock_query):
    mock_fetch.return_value = [{"result_signal": "1440"}]
    instance = _make_execution_sql()
    assert instance._freshness_changed_for_table(_make_td()) is False


@patch.object(TestExecutionSQL, "_get_query", return_value=("SELECT ...", {}))
@patch(FRESHNESS_FETCH_TARGET)
def test_freshness_changed_none_when_no_result(mock_fetch, _mock_query):
    mock_fetch.return_value = []
    instance = _make_execution_sql()
    assert instance._freshness_changed_for_table(_make_td()) is None


@patch.object(TestExecutionSQL, "_get_query", return_value=("SELECT ...", {}))
@patch(FRESHNESS_FETCH_TARGET)
def test_freshness_changed_cached_per_table(mock_fetch, _mock_query):
    """Multiple Volume/Metric defs on the same table should not re-query."""
    mock_fetch.return_value = [{"result_signal": "0"}]
    instance = _make_execution_sql()
    instance._freshness_changed_for_table(_make_td(schema_name="s", table_name="t"))
    instance._freshness_changed_for_table(_make_td(schema_name="s", table_name="t"))
    assert mock_fetch.call_count == 1


def test_resolve_cat_returns_definition_default_for_non_monitor_types():
    instance = _make_execution_sql()
    td = _make_td(test_type="Alpha_Trunc", test_operator=">=", test_condition="50")
    operator, condition = instance._resolve_cat_operator_and_condition(td)
    assert (operator, condition) == (">=", "50")


def test_resolve_cat_returns_definition_default_when_no_gating():
    """Volume_Trend / Metric_Trend with no freshness_gated flag in prediction → band check."""
    instance = _make_execution_sql()
    td = _make_td(
        test_type="Volume_Trend",
        test_operator="NOT BETWEEN",
        test_condition="{LOWER_TOLERANCE} AND {UPPER_TOLERANCE}",
        prediction={"mean": {"123": 220.0}},  # no freshness_gated
    )
    operator, condition = instance._resolve_cat_operator_and_condition(td)
    assert operator == "NOT BETWEEN"
    assert condition == "{LOWER_TOLERANCE} AND {UPPER_TOLERANCE}"


@patch.object(TestExecutionSQL, "_freshness_changed_for_table", return_value=False)
def test_resolve_cat_stale_period_overrides_to_baseline_equality(_mock_changed):
    """When freshness-gated and Freshness signal != '0' (no change), override to <> baseline."""
    instance = _make_execution_sql()
    td = _make_td(
        test_type="Volume_Trend",
        test_operator="NOT BETWEEN",
        test_condition="{LOWER_TOLERANCE} AND {UPPER_TOLERANCE}",
        prediction={"freshness_gated": True, "baseline_value": 220.0},
    )
    assert instance._resolve_cat_operator_and_condition(td) == ("<>", "220.0")


@patch.object(TestExecutionSQL, "_freshness_changed_for_table", return_value=True)
def test_resolve_cat_refresh_period_uses_band_check(_mock_changed):
    """When freshness-gated and Freshness fired this run, fall through to band check."""
    instance = _make_execution_sql()
    td = _make_td(
        test_type="Volume_Trend",
        test_operator="NOT BETWEEN",
        test_condition="{LOWER_TOLERANCE} AND {UPPER_TOLERANCE}",
        prediction={"freshness_gated": True, "baseline_value": 220.0},
    )
    operator, condition = instance._resolve_cat_operator_and_condition(td)
    assert operator == "NOT BETWEEN"
    assert condition == "{LOWER_TOLERANCE} AND {UPPER_TOLERANCE}"


@patch.object(TestExecutionSQL, "_freshness_changed_for_table", return_value=None)
def test_resolve_cat_no_freshness_result_uses_band_check(_mock_changed):
    """When no Freshness_Trend has run for this table this run, fall back to band check."""
    instance = _make_execution_sql()
    td = _make_td(
        test_type="Metric_Trend",
        test_operator="NOT BETWEEN",
        test_condition="{LOWER_TOLERANCE} AND {UPPER_TOLERANCE}",
        prediction={"freshness_gated": True, "baseline_value": 5.5},
    )
    operator, condition = instance._resolve_cat_operator_and_condition(td)
    assert operator == "NOT BETWEEN"


def test_aggregate_cat_tests_handles_null_max_query_chars():
    """A connection with NULL max_query_chars must not crash CAT batching — the
    `- 400` headroom subtraction falls back to DEFAULT_MAX_QUERY_CHARS."""
    instance = _make_execution_sql()
    instance.connection = Connection(sql_flavor="postgresql", max_query_chars=None)
    instance.flavor = "postgresql"
    instance.flavor_service = get_flavor_service("postgresql")

    td = _make_td(measure_expression="m_expr", condition_expression="c_expr")
    queries, grouped_defs = instance.aggregate_cat_tests([td], single=True)

    assert len(queries) == 1
    assert grouped_defs == [[td]]


def test_aggregate_cat_tests_read_the_location_the_run_points_at():
    """CAT builds its FROM in Python rather than through a template, so it has to follow the
    run's override the way a templated {SCHEMA_NAME} does."""
    instance = _make_execution_sql()
    instance.connection = Connection(sql_flavor="postgresql", max_query_chars=None)
    instance.flavor = "postgresql"
    instance.flavor_service = get_flavor_service("postgresql")

    td = _make_td(measure_expression="m_expr", condition_expression="c_expr")
    td.schema_name, td.table_name = "staging_a", "orders"
    td.read_schema_name, td.read_table_name = "build123", "build_orders"

    (query, _), *_ = instance.aggregate_cat_tests([td], single=True)[0]

    assert "build123" in query
    assert "build_orders" in query
    assert "staging_a" not in query


# --- TestExecutionSQL._get_params baseline guards ---


def _make_params_execution_sql() -> TestExecutionSQL:
    """Build a minimal TestExecutionSQL for exercising _get_params without a database."""
    instance = TestExecutionSQL.__new__(TestExecutionSQL)
    flavor_service = MagicMock()
    flavor_service.quote_character = '"'
    flavor_service.varchar_type = "VARCHAR"
    instance.flavor_service = flavor_service
    instance.flavor = "postgresql"
    instance.table_group = MagicMock(id=uuid4())
    instance.test_run = MagicMock(test_suite_id=uuid4(), id=uuid4())
    instance.run_date = datetime(2026, 1, 1, tzinfo=UTC)
    instance.variables = None
    return instance


@pytest.mark.parametrize(
    ("flavor", "baseline_value", "expected"),
    [
        ("postgresql", '"",n/a,"a,b"', "'', 'n/a', 'a,b'"),
        ("bigquery", "it's,a\\b", "'it\\'s', 'a\\\\b'"),
        ("postgresql", None, "NULL"),
    ],
)
def test_get_params_baseline_value_list_renders_flavor_literals(flavor, baseline_value, expected):
    instance = _make_params_execution_sql()
    instance.flavor_service = get_flavor_service(flavor)
    params = instance._get_params(_make_td(test_type="Required_No_Placeholder", baseline_value=baseline_value))
    assert params["BASELINE_VALUE_LIST"] == expected
    assert list(params)[-2:] == ["BASELINE_VALUE_LIST", "BASELINE_VALUE_LITERAL"]


@pytest.mark.parametrize(
    ("flavor", "baseline_value", "expected"),
    [
        ("postgresql", "o'brien (3), x (1)", "'o''brien (3), x (1)'"),
        ("bigquery", "it's,a\\b", "'it\\'s,a\\\\b'"),
        ("mssql", "café", "N'café'"),
        ("postgresql", "", "NULL"),
        ("postgresql", None, "NULL"),
    ],
)
def test_get_params_baseline_value_literal_renders_flavor_literal(flavor, baseline_value, expected):
    instance = _make_params_execution_sql()
    instance.flavor_service = get_flavor_service(flavor)
    params = instance._get_params(_make_td(test_type="Match_Frequent_Values", baseline_value=baseline_value))
    assert params["BASELINE_VALUE_LITERAL"] == expected


def test_baseline_value_literal_is_not_expanded_by_other_params():
    instance = _make_params_execution_sql()
    instance.flavor_service = get_flavor_service("postgresql")
    td = _make_td(test_type="Match_Frequent_Values", baseline_value="{DATA_SCHEMA} (2), {BASELINE_CT} (1)")
    query = replace_params("SELECT {BASELINE_VALUE_LITERAL} FROM {DATA_SCHEMA}.t", instance._get_params(td))
    assert query == "SELECT '{DATA_SCHEMA} (2), {BASELINE_CT} (1)' FROM public.t"


def test_get_params_value_list_follows_the_catalog_column_type():
    instance = _make_params_execution_sql()
    instance.flavor_service = get_flavor_service("postgresql")
    td = _make_td(test_type="LOV_All", column_name="amount", baseline_value="1,1.0, 2")
    td.column_chars = ColumnChars("public", "orders", "amount", general_type="N", column_type="numeric(10,2)")
    params = instance._get_params(td)
    assert params["VALUE_LIST_COLUMN"] == '"amount"'
    assert params["VALUE_LIST_LITERALS"] == "1, 2"
    assert params["VALUE_LIST_CT"] == "2"


def test_get_params_value_list_matches_text_when_the_column_is_not_in_the_catalog():
    instance = _make_params_execution_sql()
    instance.flavor_service = get_flavor_service("postgresql")
    params = instance._get_params(_make_td(test_type="LOV_Match", column_name="code", baseline_value="a,A"))
    assert params["VALUE_LIST_COLUMN"] == 'CAST("code" AS VARCHAR(1000)) COLLATE "C"'
    assert params["VALUE_LIST_CT"] == "2"


def test_get_params_value_list_is_left_out_for_other_test_types():
    instance = _make_params_execution_sql()
    instance.flavor_service = get_flavor_service("postgresql")
    td = _make_td(test_type="Constant", column_name="amount", baseline_value="abc")
    td.column_chars = ColumnChars("public", "orders", "amount", general_type="N")
    assert "VALUE_LIST_LITERALS" not in instance._get_params(td)


def test_value_list_is_not_expanded_by_any_param():
    instance = _make_params_execution_sql()
    instance.flavor_service = get_flavor_service("postgresql")
    td = _make_td(test_type="LOV_All", column_name="code", baseline_value="{DATA_SCHEMA},{VALUE_LIST_CT}")
    query = replace_params("{VALUE_LIST_LITERALS} | {VALUE_LIST_CT}", instance._get_params(td))
    assert query == "'{DATA_SCHEMA}' COLLATE \"C\", '{VALUE_LIST_CT}' COLLATE \"C\" | 2"


@pytest.mark.parametrize(
    ("field", "placeholder"),
    [
        ("custom_query", "CUSTOM_QUERY"),
        ("subset_condition", "SUBSET_CONDITION"),
        ("groupby_names", "GROUPBY_NAMES"),
        ("having_condition", "HAVING_CONDITION"),
        ("window_date_column", "WINDOW_DATE_COLUMN"),
        ("match_subset_condition", "MATCH_SUBSET_CONDITION"),
        ("match_groupby_names", "MATCH_GROUPBY_NAMES"),
        ("match_having_condition", "MATCH_HAVING_CONDITION"),
    ],
)
def test_data_schema_is_expanded_inside_user_parameters(field, placeholder):
    instance = _make_params_execution_sql()
    instance.flavor_service = get_flavor_service("postgresql")
    td = _make_td(test_type="Aggregate_Balance", **{field: "x IN (SELECT x FROM {DATA_SCHEMA}.t)"})
    query = replace_params(f"{{{placeholder}}}", instance._get_params(td))
    assert "{DATA_SCHEMA}" not in query
    assert "public.t" in query


def _subset_execution_sql() -> TestExecutionSQL:
    instance = _make_params_execution_sql()
    instance.connection = Connection(sql_flavor="postgresql", sql_flavor_code="postgresql", max_query_chars=None)
    instance.flavor_service = get_flavor_service("postgresql")
    return instance


def test_subset_is_evaluated_once_per_record_and_read_by_the_measure():
    instance = _subset_execution_sql()
    td = _make_td(
        test_type="Required", measure="COUNT({SUBSET_ROW}) - COUNT({COLUMN_NAME})",
        subset_condition="status = 'X' OR status IS NULL",
    )
    [(query, _)], _ = instance.aggregate_cat_tests([td])
    flag = instance._subset_flag(td)
    assert f'COUNT({flag}) - COUNT((CASE WHEN {flag} = 1 THEN "amount" END))' in td.measure_expression
    assert query.endswith(
        f"FROM (SELECT \"orders\".*, CASE WHEN (status = 'X' OR status IS NULL) THEN 1 END AS {flag} "
        'FROM "public"."orders" "orders") "orders"'
    )
    assert query.count("status = 'X'") == 1


def test_tests_with_one_subset_share_its_column_in_one_query():
    instance = _subset_execution_sql()
    test_defs = [
        _make_td(measure="COUNT({COLUMN_NAME})", subset_condition="a = 1"),
        _make_td(measure="MAX({COLUMN_NAME})", subset_condition="a = 1"),
        _make_td(measure="MIN({COLUMN_NAME})", subset_condition="b = 2"),
        _make_td(measure="COUNT({COLUMN_NAME})"),
    ]
    queries, groups = instance.aggregate_cat_tests(test_defs)
    assert len(queries) == 1 and len(groups[0]) == 4
    query = queries[0][0]
    assert query.count("CASE WHEN (a = 1) THEN 1 END") == 1
    assert query.count("CASE WHEN (b = 2) THEN 1 END") == 1
    assert instance._subset_flag(test_defs[0]) != instance._subset_flag(test_defs[2])


def test_query_without_a_subset_reads_the_table_directly():
    instance = _subset_execution_sql()
    td = _make_td(test_type="Required", measure="COUNT({SUBSET_ROW}) - COUNT({COLUMN_NAME})")
    [(query, _)], _ = instance.aggregate_cat_tests([td])
    assert td.measure_expression.startswith('COALESCE(CAST(COUNT(*) - COUNT("amount") AS')
    assert query.endswith('FROM "public"."orders"')


def test_blank_subset_reads_the_table_directly():
    instance = _subset_execution_sql()
    td = _make_td(test_type="Required", measure="COUNT({SUBSET_ROW}) - COUNT({COLUMN_NAME})", subset_condition="  ")
    [(query, _)], _ = instance.aggregate_cat_tests([td])
    assert td.measure_expression.startswith('COALESCE(CAST(COUNT(*) - COUNT("amount") AS')
    assert query.endswith('FROM "public"."orders"')
    assert instance._get_params(td)["SUBSET_CONDITION"] == "1=1"


def test_custom_query_subset_reads_the_subset_column():
    instance = _subset_execution_sql()
    td = _make_td(
        test_type="Volume_Trend", measure="{CUSTOM_QUERY}",
        custom_query="COUNT(CASE WHEN {SUBSET_CONDITION} THEN 1 END)", subset_condition="a = 1",
    )
    instance.aggregate_cat_tests([td])
    assert f"COUNT(CASE WHEN {instance._subset_flag(td)} = 1 THEN 1 END)" in td.measure_expression


def test_data_schema_is_expanded_inside_a_subset():
    instance = _subset_execution_sql()
    td = _make_td(
        test_type="LOV_Match", column_name="code", baseline_value="a",
        measure="SUM(CASE WHEN {VALUE_LIST_COLUMN} NOT IN ({VALUE_LIST_LITERALS}) THEN 1 ELSE 0 END)",
        subset_condition="id IN (SELECT id FROM {DATA_SCHEMA}.t)",
    )
    [(query, _)], _ = instance.aggregate_cat_tests([td])
    assert "{DATA_SCHEMA}" not in query
    assert "id IN (SELECT id FROM public.t)" in query


def test_a_shared_subset_counts_once_against_the_query_length():
    instance = _subset_execution_sql()
    instance.connection.max_query_chars = 4500
    long_subset = "status IN (" + ", ".join(f"'{n:04}'" for n in range(250)) + ")"
    test_defs = [_make_td(measure="COUNT({COLUMN_NAME})", subset_condition=long_subset) for _ in range(5)]
    queries, _ = instance.aggregate_cat_tests(test_defs)
    assert len(queries) == 1
    assert len(queries[0][0]) <= 4500


def test_queries_reading_a_subset_of_a_long_named_table_fit_the_query_length():
    instance = _subset_execution_sql()
    instance.connection.max_query_chars = 6000
    test_defs = [
        _make_td(
            measure="MAX({COLUMN_NAME})",
            column_name=f"column_{n}",
            schema_name="s" * 120,
            table_name="t" * 120,
            subset_condition="status = 'SHIPPED'",
        )
        for n in range(40)
    ]
    queries, _ = instance.aggregate_cat_tests(test_defs)
    assert len(queries) > 1
    assert max(len(query) for query, _ in queries) <= 6000


def test_run_query_test_renders_inline_template_unbound():
    instance = _make_params_execution_sql()
    instance.flavor_service = get_flavor_service("postgresql")
    td = _make_td(
        test_type="Match_Frequent_Values",
        run_type="QUERY",
        template="SELECT {BASELINE_VALUE_LITERAL}::TEXT FROM {DATA_SCHEMA}.t",
        baseline_value="a :b (1)",
    )
    query, params = instance.run_query_test(td)
    assert query == "SELECT 'a \\:b (1)'\\:\\:TEXT FROM public.t"
    assert params is None


def test_get_params_custom_query_drops_trailing_semicolons():
    instance = _make_params_execution_sql()
    params = instance._get_params(_make_td(test_type="CUSTOM", custom_query="SELECT * FROM t WHERE x < 0;\n"))
    assert params["CUSTOM_QUERY"] == "SELECT * FROM t WHERE x < 0"


def test_get_params_empty_baseline_counts_become_null():
    """Empty baseline counts must render as NULL, not "", to avoid CAST( AS FLOAT) syntax errors."""
    instance = _make_params_execution_sql()
    params = instance._get_params(_make_td(test_type="Missing_Pct", baseline_ct="", baseline_value_ct=""))
    assert params["BASELINE_CT"] == "NULL"
    assert params["BASELINE_VALUE_CT"] == "NULL"


def test_get_params_none_baseline_counts_become_null():
    instance = _make_params_execution_sql()
    params = instance._get_params(_make_td(test_type="Missing_Pct", baseline_ct=None, baseline_value_ct=None))
    assert params["BASELINE_CT"] == "NULL"
    assert params["BASELINE_VALUE_CT"] == "NULL"


def test_get_params_populated_baseline_counts_pass_through():
    instance = _make_params_execution_sql()
    params = instance._get_params(_make_td(test_type="Missing_Pct", baseline_ct="1000", baseline_value_ct="950"))
    assert params["BASELINE_CT"] == "1000"
    assert params["BASELINE_VALUE_CT"] == "950"


def test_get_params_zero_baseline_count_is_not_nulled():
    """A real 0 is a meaningful value and must not be coerced to NULL."""
    instance = _make_params_execution_sql()
    params = instance._get_params(_make_td(test_type="Row_Ct_Pct", baseline_ct=0))
    assert params["BASELINE_CT"] == 0


# --- One run writes one test_time ---

# Microseconds are deliberate: they must not reach test_time, which every result path writes at
# the whole-second precision of the {RUN_DATE} the QUERY and METADATA templates interpolate.
RUN_STARTTIME = datetime(2026, 7, 14, 21, 22, 26, 227897, tzinfo=UTC)

TEST_TIME_INDEX = TestExecutionSQL.result_columns.index("test_time")


def _make_result_execution_sql() -> TestExecutionSQL:
    """Build a minimal TestExecutionSQL for exercising the result-row builders without a database."""
    instance = _make_params_execution_sql()
    instance.run_date = RUN_STARTTIME
    return instance


def test_cat_result_rows_carry_the_run_date_the_templates_interpolate():
    instance = _make_result_execution_sql()
    td = _make_td(test_type="Alpha")
    results = [{"query_index": 0, "result_measures": "42|", "result_codes": "1,"}]

    row = instance.get_cat_test_results(results, [[td]])[0]

    assert row[TEST_TIME_INDEX] == instance._get_params()["RUN_DATE"]
    assert row[TEST_TIME_INDEX] == "2026-07-14 21:22:26"


def test_error_result_rows_carry_the_same_test_time_as_cat_rows():
    instance = _make_result_execution_sql()
    td = _make_td(test_type="Alpha", errors=["unsupported type"])
    results = [{"query_index": 0, "result_measures": "42|", "result_codes": "1,"}]

    cat_row = instance.get_cat_test_results(results, [[_make_td(test_type="Alpha")]])[0]
    error_row = instance.get_test_errors([td])[0]

    # A run writes one test_time: every result row of a run must carry the same value, whatever
    # path produced it. The scoring views group on test_run_id plus test_time, so a run that
    # writes two values splits one column's tests into two score rows.
    assert error_row[TEST_TIME_INDEX] == cat_row[TEST_TIME_INDEX]
    assert error_row[TEST_TIME_INDEX] == instance._get_params()["RUN_DATE"]


def test_get_params_empty_numeric_baselines_become_null():
    """All numeric baseline params render NULL when empty."""
    instance = _make_params_execution_sql()
    params = instance._get_params(_make_td(
        test_type="Avg_Shift",
        baseline_unique_ct="", baseline_avg="", baseline_sd="", baseline_sum="",
    ))
    assert params["BASELINE_UNIQUE_CT"] == "NULL"
    assert params["BASELINE_AVG"] == "NULL"
    assert params["BASELINE_SD"] == "NULL"
    # Non-Freshness test types null-guard BASELINE_SUM (numeric use in Incr_Avg_Shift)
    assert params["BASELINE_SUM"] == "NULL"


def test_get_params_freshness_baseline_sum_kept_raw_when_empty():
    """Freshness_Trend quotes BASELINE_SUM (NULLIF('', '') in template) — must stay empty, not 'NULL'."""
    instance = _make_params_execution_sql()
    params = instance._get_params(_make_td(test_type="Freshness_Trend", baseline_sum=""))
    assert params["BASELINE_SUM"] == ""


def test_get_params_baseline_value_left_unguarded():
    """BASELINE_VALUE has non-uniform usage (quoted/number/IN-list) — not coerced to NULL."""
    instance = _make_params_execution_sql()
    params = instance._get_params(_make_td(test_type="Constant", baseline_value=""))
    assert params["BASELINE_VALUE"] == ""


def test_get_params_empty_tolerances_become_null():
    """Tolerances use the same NULL guard."""
    instance = _make_params_execution_sql()
    params = instance._get_params(_make_td(test_type="Volume_Trend", lower_tolerance="", upper_tolerance=""))
    assert params["LOWER_TOLERANCE"] == "NULL"
    assert params["UPPER_TOLERANCE"] == "NULL"




# --- TestExecutionSQL freshness exclusion params ---


def _make_freshness_execution_sql(run_date, exclude_weekends=False, holiday_dates=None) -> TestExecutionSQL:
    instance = TestExecutionSQL.__new__(TestExecutionSQL)
    instance.run_date = run_date
    instance._exclude_weekends = exclude_weekends
    instance._holiday_dates = holiday_dates
    instance._schedule_tz = "UTC"
    return instance


def _freshness_td(prediction=None, last_update="2026-12-24 06:00:00"):
    return _make_td(test_type="Freshness_Trend", baseline_sum=last_update, prediction=prediction)


def test_freshness_exclusions_count_holidays_without_other_exclusions():
    instance = _make_freshness_execution_sql(datetime(2026, 12, 25, 12, 0), holiday_dates={date(2026, 12, 25)})
    params = instance._freshness_exclusion_params(_freshness_td())
    assert params == {"EXCLUDED_MINUTES": 12 * 60, "IS_EXCLUDED_DAY": 1}


def test_freshness_exclusions_zero_without_any_exclusions():
    instance = _make_freshness_execution_sql(datetime(2026, 12, 25, 12, 0))
    assert instance._freshness_exclusion_params(_freshness_td()) == {"EXCLUDED_MINUTES": 0, "IS_EXCLUDED_DAY": 0}


def test_freshness_exclusions_full_week_schedule_overrides_weekend_setting():
    prediction = {"schedule_stage": "active", "active_days": list(range(7))}
    instance = _make_freshness_execution_sql(datetime(2026, 9, 26, 12, 0), exclude_weekends=True)  # Saturday
    params = instance._freshness_exclusion_params(_freshness_td(prediction, last_update="2026-09-25 06:00:00"))
    assert params == {"EXCLUDED_MINUTES": 0, "IS_EXCLUDED_DAY": 0}


def test_freshness_exclusions_skip_other_test_types():
    instance = _make_freshness_execution_sql(datetime(2026, 12, 25, 12, 0), holiday_dates={date(2026, 12, 25)})
    td = _make_td(test_type="Volume_Trend", baseline_sum="2026-12-24 06:00:00")
    assert instance._freshness_exclusion_params(td) == {"EXCLUDED_MINUTES": 0, "IS_EXCLUDED_DAY": 0}


# --- schema on the execution path ---


def _make_schema_execution_sql() -> TestExecutionSQL:
    """Build a TestExecutionSQL through __init__ so schema resolution is exercised."""
    table_group = MagicMock(id=uuid4(), table_group_schema="test_schema")
    test_suite = MagicMock(suite_type=SuiteType.STANDARD, predict_exclude_weekends=False, id=uuid4())
    test_run = MagicMock(id=uuid4(), test_suite_id=uuid4(), test_starttime=datetime(2026, 1, 1, tzinfo=UTC))
    return TestExecutionSQL(Connection(sql_flavor="postgresql"), table_group, test_suite, test_run)


def test_the_table_group_schema_reaches_the_validation_query():
    """Validation resolves identifiers in the schema the table group reads, which is the one its
    tests run against."""
    _query, params = _make_schema_execution_sql().get_target_identifiers("test_schema")

    assert params["DATA_SCHEMA"] == "test_schema"
    assert params["TEST_SCHEMAS"] == "'test_schema'"


def test_the_test_definition_drives_the_executed_sql():
    """Every schema read on the execution path goes through ``TestExecutionDef.schema_name``.

    A refactor sourcing the schema from the table group instead would run against the wrong one
    whenever the two disagree, while reporting success.
    """
    sql_generator = _make_schema_execution_sql()
    td = _make_td(schema_name="onboard_2026_09_10", measure="COUNT(*)", test_condition="100")

    queries, groups = sql_generator.aggregate_cat_tests([td])

    assert '"onboard_2026_09_10"."orders"' in queries[0][0]
    assert "test_schema" not in queries[0][0]
    assert groups == [[td]]


def test_the_test_definition_drives_the_recorded_result_schema():
    """Results carry the schema the run read, which the score rollup joins on."""
    sql_generator = _make_schema_execution_sql()
    td = _make_td(schema_name="onboard_2026_09_10", errors=["Deactivated", "Missing table: x"])

    (row,) = sql_generator.get_test_errors([td])

    assert row[TestExecutionSQL.result_columns.index("schema_name")] == "onboard_2026_09_10"


def test_the_match_schema_is_independent_of_the_test_s_own():
    """A referential test compares against a table outside the table group, so the two schemas
    are separate inputs -- a run retargets the match side alone."""
    sql_generator = _make_schema_execution_sql()
    td = _make_td(
        schema_name="onboard_2026_09_10",
        match_schema_name="reference_2026_09_16",
        match_table_name="orders",
        match_column_names="customer_id",
    )

    params = sql_generator._get_params(td)

    assert params["SCHEMA_NAME"] == "onboard_2026_09_10"
    assert params["MATCH_SCHEMA_NAME"] == "reference_2026_09_16"


# --- the location a run reads ---


def _column(table_name: str, column_name: str, **overrides) -> ColumnChars:
    defaults = {
        "schema_name": "build_20261104",
        "table_name": table_name,
        "column_name": column_name,
        "general_type": "A",
        "db_data_type": "varchar(50)",
        "logical_type": "string",
    }
    defaults.update(overrides)
    return ColumnChars(**defaults)


def test_a_retargeted_test_reads_its_run_s_table_and_reports_its_own():
    """The two names are separate parameters: the FROM clause takes the table the run reads, and
    anything scoped to the table group takes the one the test is defined on."""
    sql_generator = _make_schema_execution_sql()
    td = _make_td(schema_name="public", table_name="orders")
    td.read_schema_name = "build_20261104"
    td.read_table_name = "build_orders"

    params = sql_generator._get_params(td)

    assert params["SCHEMA_NAME"] == "build_20261104"
    assert params["TABLE_NAME"] == "build_orders"
    assert params["DATA_SCHEMA"] == "build_20261104"
    assert params["CATALOG_TABLE_NAME"] == "orders"


def test_a_test_the_run_leaves_alone_reads_its_own_table():
    sql_generator = _make_schema_execution_sql()
    params = sql_generator._get_params(_make_td(schema_name="public", table_name="orders"))

    assert params["TABLE_NAME"] == "orders"
    assert params["CATALOG_TABLE_NAME"] == "orders"


def test_observed_columns_come_from_the_catalog_when_the_run_reads_the_table_group():
    """The catalog describes the table group, so it is matched on the definition's table name."""
    sql_generator = _make_schema_execution_sql()
    td = _make_td(table_name="orders")

    source = sql_generator._observed_columns(td)

    assert "data_column_chars" in source
    assert "table_name = 'orders'" in source
    assert "drop_date IS NULL" in source


def test_observed_columns_come_from_the_run_when_it_reads_elsewhere():
    """A metadata test describes what the run read, not what the catalog holds."""
    sql_generator = _make_schema_execution_sql()
    sql_generator.run_columns = [
        _column("build_orders", "id", general_type="N", db_data_type="integer", logical_type="integer"),
        _column("build_orders", "name"),
        _column("other_table", "unrelated"),
    ]
    td = _make_td(table_name="orders")
    td.read_schema_name = "build_20261104"
    td.read_table_name = "build_orders"

    source = sql_generator._observed_columns(td)

    assert "data_column_chars" not in source
    assert source.startswith("(VALUES ")
    assert "('id', 'N', 'integer', 'integer')" in source
    assert "('name', 'A', 'varchar(50)', 'string')" in source
    assert "unrelated" not in source
    assert source.endswith(") oc(column_name, general_type, db_data_type, logical_type)")


def test_observed_columns_are_empty_when_the_run_s_table_is_missing():
    """A table the run does not hold yields no rows, so a count fails and a conformance test
    reports the table missing."""
    sql_generator = _make_schema_execution_sql()
    sql_generator.run_columns = [_column("something_else", "id")]
    td = _make_td(table_name="orders")
    td.read_schema_name = "build_20261104"
    td.read_table_name = "build_orders"

    source = sql_generator._observed_columns(td)

    assert "WHERE FALSE" in source
    assert "VALUES" not in source


def test_observed_columns_match_a_table_case_insensitively_when_no_name_matches_exactly():
    """A flavor that folds identifiers returns them in its own case."""
    sql_generator = _make_schema_execution_sql()
    sql_generator.run_columns = [_column("BUILD_ORDERS", "ID", schema_name="BUILD_20261104")]
    td = _make_td(table_name="orders")
    td.read_schema_name = "build_20261104"
    td.read_table_name = "build_orders"

    assert "'ID'" in sql_generator._observed_columns(td)


def test_a_quote_in_an_observed_column_name_is_escaped():
    sql_generator = _make_schema_execution_sql()
    sql_generator.run_columns = [_column("build_orders", "it's")]
    td = _make_td(table_name="orders")
    td.read_schema_name = "build_20261104"
    td.read_table_name = "build_orders"

    assert "'it''s'" in sql_generator._observed_columns(td)


def test_an_unknown_observed_type_is_a_typed_null():
    """An untyped NULL in a VALUES list leaves the column with no type."""
    sql_generator = _make_schema_execution_sql()
    sql_generator.run_columns = [_column("build_orders", "id", logical_type=None)]
    td = _make_td(table_name="orders")
    td.read_schema_name = "build_20261104"
    td.read_table_name = "build_orders"

    source = sql_generator._observed_columns(td)

    # The empty source is all typed NULLs, so the row has to be there for this to mean anything.
    assert source.startswith("(VALUES ")
    assert "('id', 'A', 'varchar(50)', CAST(NULL AS VARCHAR))" in source


def test_only_a_template_that_reads_observed_columns_is_given_them():
    """Rendering a table's whole column list for every test in a run would be wasted on the ones
    that never reference it."""
    sql_generator = _make_schema_execution_sql()

    reader = _make_td(table_name="orders", template="SELECT COUNT(*) FROM {OBSERVED_COLUMNS}")
    assert "data_column_chars" in sql_generator._get_params(reader)["OBSERVED_COLUMNS"]

    other = _make_td(table_name="orders", template="SELECT COUNT(*) FROM {DATA_SCHEMA}.orders")
    assert sql_generator._get_params(other)["OBSERVED_COLUMNS"] == ""


# --- the parameters a result records ---


def _input_params_sql(flavor: str) -> TestExecutionSQL:
    instance = _make_params_execution_sql()
    instance.flavor = flavor
    instance.flavor_service = get_flavor_service(flavor)
    return instance


def test_a_type_that_declares_a_custom_query_records_the_one_it_ran():
    """The query is the test, and a run giving one of its variables a value changes what ran, so
    the result carries the text that ran rather than the declaration."""
    instance = _input_params_sql("postgresql")
    td = _make_td(
        test_type="CUSTOM",
        default_parm_columns="custom_query,match_column_names,skip_errors",
        custom_query="SELECT id FROM orders WHERE total < 0",
    )

    assert "custom_query=SELECT id FROM orders WHERE total < 0" in instance._get_input_parameters(td)


def test_a_type_that_builds_its_own_query_records_none():
    """Freshness_Trend keeps a generated fingerprint expression in the same column. It describes
    the type rather than how the test was set up, and runs to thousands of characters."""
    instance = _input_params_sql("postgresql")
    td = _make_td(
        test_type="Freshness_Trend",
        default_parm_columns="threshold_value,history_calculation",
        custom_query='COUNT(*)::VARCHAR || \'|\' || MIN("sale_date")::VARCHAR',
    )

    assert "custom_query" not in instance._get_input_parameters(td)


def test_the_parameters_a_user_set_are_recorded_either_way():
    """Only the query is held back, so a type that generates one still reports its own setup."""
    instance = _input_params_sql("postgresql")
    td = _make_td(
        test_type="Freshness_Trend",
        default_parm_columns="threshold_value",
        custom_query="MIN(x)",
        threshold_value="7",
    )

    assert "threshold_value=7" in instance._get_input_parameters(td)


@pytest.mark.parametrize("flavor", ["bigquery", "databricks", "snowflake", "redshift"])
def test_a_backslash_is_doubled_where_the_flavor_reads_one_as_an_escape(flavor):
    """The template wraps this string in quotes of its own. Left alone, the backslash of a regex
    forms an escape sequence the flavor rejects, and a trailing one escapes the closing quote."""
    instance = _input_params_sql(flavor)
    td = _make_td(
        test_type="SQL_Metric",
        default_parm_columns="custom_query",
        custom_query=r"SELECT COUNT(*) FROM t WHERE REGEXP_CONTAINS(code, r'\d+')",
    )

    assert r"r`\\d+`" in instance._input_parameters_literal(td)


def test_a_backslash_stands_where_the_flavor_reads_it_literally():
    instance = _input_params_sql("postgresql")
    td = _make_td(
        test_type="SQL_Metric",
        default_parm_columns="custom_query",
        custom_query=r"SELECT COUNT(*) FROM t WHERE path LIKE 'a\b'",
    )

    assert r"`a\b`" in instance._input_parameters_literal(td)


def test_a_long_record_is_cut_to_what_the_flavor_accepts():
    """Oracle rejects a string literal over 4,000 bytes with ORA-01704, which would error the
    test rather than shorten its record of what it ran."""
    instance = _input_params_sql("oracle")
    td = _make_td(
        test_type="CUSTOM",
        default_parm_columns="custom_query",
        custom_query="SELECT id FROM orders WHERE note = `" + "a" * 5000 + "`",
    )

    recorded = instance._input_parameters_literal(td)

    assert len(recorded.encode()) == 4000
    assert recorded.endswith("...")


def test_a_record_the_flavor_accepts_is_left_whole():
    instance = _input_params_sql("oracle")
    td = _make_td(test_type="CUSTOM", default_parm_columns="custom_query", custom_query="SELECT 1")

    assert instance._input_parameters_literal(td) == "custom_query=SELECT 1"


@pytest.mark.parametrize("flavor", ["bigquery", "oracle"])
def test_a_row_written_to_the_application_database_is_neither_escaped_nor_cut(flavor):
    """A CAT result and an error row are written by COPY in CSV, which reads a backslash as a
    backslash, so escaping one would store text the query never held. The cut goes with it: the
    length a flavor caps is the literal in its own SQL, not a column of the application's."""
    instance = _input_params_sql(flavor)
    td = _make_td(
        test_type="Condition_Flag",
        default_parm_columns="threshold_value,custom_query",
        custom_query=r"code ~ '\d+' AND note <> '" + "a" * 5000 + "'",
    )

    recorded = instance._get_input_parameters(td)

    assert r"`\d+`" in recorded
    assert len(recorded.encode()) > 5000
