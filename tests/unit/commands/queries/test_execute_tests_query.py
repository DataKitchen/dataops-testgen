from datetime import UTC, datetime
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
from testgen.common.database.database_service import get_flavor_service
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
    start = datetime.now(UTC)

    rows = parse_cat_results(results, test_defs, run_id, suite_id, start,
                              _make_input_params_fn())
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == run_id
    assert row[1] == suite_id
    assert row[2] == start
    assert row[3] == td.id
    assert row[10] == "1"  # result_code
    assert row[13] == "42"  # result_measure


def test_parse_null_value_handling():
    td = _make_td()
    test_defs = [[td]]
    results = [{"query_index": 0, "result_measures": f"<NULL>{MEASURE_SEPARATOR}", "result_codes": "0,"}]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              datetime.now(UTC), _make_input_params_fn())
    assert rows[0][13] is None  # <NULL> should become None


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
                              datetime.now(UTC), _make_input_params_fn())
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
                              datetime.now(UTC), _make_input_params_fn())
    assert len(rows) == 2
    assert rows[0][4] == "Alpha"
    assert rows[1][4] == "Beta"


def test_parse_result_code_negative_one():
    """Training mode result (-1) should pass through."""
    td = _make_td()
    test_defs = [[td]]
    results = [{"query_index": 0, "result_measures": f"42{MEASURE_SEPARATOR}", "result_codes": "-1,"}]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              datetime.now(UTC), _make_input_params_fn())
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
    return instance


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


