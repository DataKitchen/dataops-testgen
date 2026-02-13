from datetime import datetime, UTC
from uuid import uuid4

import pytest

from testgen.commands.queries.execute_tests_query import (
    TestExecutionDef,
    build_cat_expressions,
    group_cat_tests,
    parse_cat_results,
)

pytestmark = pytest.mark.unit


def _make_td(**overrides) -> TestExecutionDef:
    """Build a minimal TestExecutionDef with sensible defaults."""
    defaults = dict(
        id=uuid4(),
        test_type="Alpha",
        schema_name="public",
        table_name="orders",
        column_name="amount",
        skip_errors=0,
        history_calculation="NONE",
        custom_query="",
        run_type="CAT",
        test_scope="column",
        template="",
        measure="COUNT(*)",
        test_operator=">=",
        test_condition="100",
        baseline_ct="",
        baseline_unique_ct="",
        baseline_value="",
        baseline_value_ct="",
        threshold_value="",
        baseline_sum="",
        baseline_avg="",
        baseline_sd="",
        lower_tolerance="",
        upper_tolerance="",
        subset_condition="",
        groupby_names="",
        having_condition="",
        window_date_column="",
        window_days="",
        match_schema_name="",
        match_table_name="",
        match_column_names="",
        match_subset_condition="",
        match_groupby_names="",
        match_having_condition="",
    )
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
    assert "'|'" in measure_expr
    assert "<NULL>|" in measure_expr


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
    assert "'MISSING|'" in measure_expr


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
    results = [{"query_index": 0, "result_measures": "42|", "result_codes": "1,"}]
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
    results = [{"query_index": 0, "result_measures": "<NULL>|", "result_codes": "0,"}]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              datetime.now(UTC), _make_input_params_fn())
    assert rows[0][13] is None  # <NULL> should become None


def test_parse_multi_test_per_query():
    td1 = _make_td(test_type="Alpha")
    td2 = _make_td(test_type="Beta")
    test_defs = [[td1, td2]]
    results = [{"query_index": 0, "result_measures": "10|20|", "result_codes": "1,0,"}]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              datetime.now(UTC), _make_input_params_fn())
    assert len(rows) == 2
    assert rows[0][13] == "10"
    assert rows[1][13] == "20"
    assert rows[0][10] == "1"
    assert rows[1][10] == "0"


def test_parse_multiple_queries():
    td1 = _make_td(test_type="Alpha")
    td2 = _make_td(test_type="Beta")
    test_defs = [[td1], [td2]]
    results = [
        {"query_index": 0, "result_measures": "10|", "result_codes": "1,"},
        {"query_index": 1, "result_measures": "20|", "result_codes": "0,"},
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
    results = [{"query_index": 0, "result_measures": "42|", "result_codes": "-1,"}]

    rows = parse_cat_results(results, test_defs, uuid4(), uuid4(),
                              datetime.now(UTC), _make_input_params_fn())
    assert rows[0][10] == "-1"
