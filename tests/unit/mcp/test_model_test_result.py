from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.test_result import (
    TestResult,
    TestResultStatus,
    TestRunResultRow,
    _parse_kv_pairs,
)


@pytest.fixture
def session_mock():
    with patch("testgen.common.models.test_result.get_current_session") as mock:
        yield mock.return_value


def _compiled_sql(captured_query) -> str:
    return str(captured_query.compile(dialect=postgresql.dialect()))


def test_select_results_basic(session_mock):
    mock_results = [MagicMock(spec=TestResult)]
    session_mock.scalars.return_value.all.return_value = mock_results

    results = TestResult.select_results(test_run_id=uuid4())

    assert results == mock_results
    session_mock.scalars.assert_called_once()


def test_select_results_with_status_filter(session_mock):
    session_mock.scalars.return_value.all.return_value = []

    results = TestResult.select_results(test_run_id=uuid4(), status=TestResultStatus.Failed)

    assert results == []


def test_select_results_with_all_filters(session_mock):
    session_mock.scalars.return_value.all.return_value = []

    results = TestResult.select_results(
        test_run_id=uuid4(),
        status=TestResultStatus.Passed,
        table_name="orders",
        test_type="Alpha_Trunc",
        limit=10,
    )

    assert results == []


def test_select_failures_by_test_type(session_mock):
    session_mock.execute.return_value.all.return_value = [
        ("Alpha_Trunc", TestResultStatus.Failed, 5),
        ("Unique_Pct", TestResultStatus.Warning, 3),
    ]

    results = TestResult.select_failures(test_run_id=uuid4(), group_by="test_type")

    assert len(results) == 2
    assert results[0] == ("Alpha_Trunc", TestResultStatus.Failed, 5)


def test_select_failures_by_table_name(session_mock):
    session_mock.execute.return_value.all.return_value = [("orders", 8)]

    results = TestResult.select_failures(test_run_id=uuid4(), group_by="table_name")

    assert results[0] == ("orders", 8)


def test_select_failures_by_column_names(session_mock):
    session_mock.execute.return_value.all.return_value = [("orders", "customer_name", 4)]

    results = TestResult.select_failures(test_run_id=uuid4(), group_by="column_names")

    assert results[0] == ("orders", "customer_name", 4)


def test_select_failures_invalid_group_by():
    with pytest.raises(ValueError, match="group_by must be one of"):
        TestResult.select_failures(test_run_id=uuid4(), group_by="invalid_column")


def test_select_failures_empty(session_mock):
    session_mock.execute.return_value.all.return_value = []

    results = TestResult.select_failures(test_run_id=uuid4())

    assert results == []


def test_select_history_basic(session_mock):
    mock_results = [MagicMock(spec=TestResult), MagicMock(spec=TestResult)]
    session_mock.scalars.return_value.all.return_value = mock_results

    results = TestResult.select_history(test_definition_id=uuid4())

    assert results == mock_results
    session_mock.scalars.assert_called_once()


def test_select_history_empty(session_mock):
    session_mock.scalars.return_value.all.return_value = []

    results = TestResult.select_history(test_definition_id=uuid4(), limit=10)

    assert results == []


def test_select_results_excludes_monitor_suites(session_mock):
    session_mock.scalars.return_value.all.return_value = []

    TestResult.select_results(test_run_id=uuid4())

    sql = _compiled_sql(session_mock.scalars.call_args[0][0])
    assert "test_suites.is_monitor IS NOT true" in sql
    assert "JOIN test_suites" in sql


def test_select_results_excludes_monitor_suites_with_project_codes(session_mock):
    session_mock.scalars.return_value.all.return_value = []

    TestResult.select_results(test_run_id=uuid4(), project_codes=["demo"])

    sql = _compiled_sql(session_mock.scalars.call_args[0][0])
    assert "test_suites.is_monitor IS NOT true" in sql
    assert "test_suites.project_code IN" in sql


def test_list_for_run_excludes_monitor_suites():
    with patch.object(TestResult, "_paginate", return_value=([], 0)) as mock_paginate:
        TestResult.list_for_run(uuid4())

    sql = _compiled_sql(mock_paginate.call_args.args[0])
    assert "test_suites.is_monitor IS NOT true" in sql
    assert "JOIN test_suites" in sql


def test_list_for_run_applies_caller_clauses_and_pagination():
    with patch.object(TestResult, "_paginate", return_value=([], 0)) as mock_paginate:
        TestResult.list_for_run(uuid4(), TestResult.table_name == "orders", page=3, limit=10)

    sql = _compiled_sql(mock_paginate.call_args.args[0])
    assert "test_results.table_name = " in sql
    assert mock_paginate.call_args.kwargs["page"] == 3
    assert mock_paginate.call_args.kwargs["limit"] == 10
    assert mock_paginate.call_args.kwargs["data_class"] is TestRunResultRow


def test_select_failures_excludes_monitor_suites(session_mock):
    session_mock.execute.return_value.all.return_value = []

    TestResult.select_failures(test_run_id=uuid4(), group_by="test_type")

    sql = _compiled_sql(session_mock.execute.call_args[0][0])
    assert "test_suites.is_monitor IS NOT true" in sql
    assert "JOIN test_suites" in sql


def test_select_history_excludes_monitor_suites(session_mock):
    session_mock.scalars.return_value.all.return_value = []

    TestResult.select_history(test_definition_id=uuid4())

    sql = _compiled_sql(session_mock.scalars.call_args[0][0])
    assert "test_suites.is_monitor IS NOT true" in sql
    assert "JOIN test_suites" in sql


# ---------------------------------------------------------------------------
# _parse_kv_pairs — contract with the producer of ``input_parameters``
# ---------------------------------------------------------------------------


def test_parse_kv_pairs_splits_on_semicolon_for_multi_field_input():
    """``input_parameters`` is built with ``"; ".join(...)`` on the writer side
    and consumed by ``dict_from_kv`` with ``;`` as the default separator. The
    parser must agree, otherwise a row carrying both ``lower_tolerance`` and
    ``upper_tolerance`` returns one entry with the second pair embedded in the
    first value, and the upper bound never surfaces."""
    raw = "lower_tolerance=5; upper_tolerance=10; baseline_value=42"
    assert _parse_kv_pairs(raw) == {
        "lower_tolerance": "5",
        "upper_tolerance": "10",
        "baseline_value": "42",
    }


def test_parse_kv_pairs_returns_empty_for_empty_input():
    assert _parse_kv_pairs(None) == {}
    assert _parse_kv_pairs("") == {}


def test_parse_kv_pairs_tolerates_whitespace_and_skips_unkeyed_entries():
    raw = "  k1 = v1  ;k2=v2; just_text ; k3=v3"
    assert _parse_kv_pairs(raw) == {"k1": "v1", "k2": "v2", "k3": "v3"}


# ---------------------------------------------------------------------------
# list_monitor_events_for_table — ORDER BY needs a stable tiebreaker because
# the result is then paginated in Python; without it a row sharing ``test_time``
# with another can duplicate or skip across pages.
# ---------------------------------------------------------------------------


def test_list_monitor_events_for_table_orders_by_stable_tiebreaker(session_mock):
    session_mock.execute.return_value.mappings.return_value.all.return_value = []

    TestResult.list_monitor_events_for_table(uuid4(), "orders")

    raw_sql = str(session_mock.execute.call_args[0][0])
    order_clause = raw_sql.split("ORDER BY", 1)[1]
    assert "results.id" in order_clause
    assert "active_runs.id" in order_clause


# ---------------------------------------------------------------------------
# list_metric_monitor_events — scoped to one test_definition_id, separate
# query path from the run-by-type CTE (no synthesized pending rows).
# ---------------------------------------------------------------------------


def test_list_metric_monitor_events_scopes_to_test_definition_id(session_mock):
    session_mock.execute.return_value.mappings.return_value.all.return_value = []

    suite_id = uuid4()
    monitor_id = uuid4()
    TestResult.list_metric_monitor_events(suite_id, monitor_id)

    raw_sql = str(session_mock.execute.call_args[0][0])
    params = session_mock.execute.call_args[0][1]
    assert "results.test_definition_id = :test_definition_id" in raw_sql
    assert "results.test_suite_id = :test_suite_id" in raw_sql
    assert params["test_definition_id"] == str(monitor_id)
    assert params["test_suite_id"] == str(suite_id)


def test_list_metric_monitor_events_has_stable_order_with_tiebreaker(session_mock):
    """Like the multi-type CTE, this path paginates in Python — the ORDER BY
    must include a tiebreaker so rows sharing ``test_time`` don't shuffle
    between calls."""
    session_mock.execute.return_value.mappings.return_value.all.return_value = []

    TestResult.list_metric_monitor_events(uuid4(), uuid4())

    raw_sql = str(session_mock.execute.call_args[0][0])
    order_clause = raw_sql.split("ORDER BY", 1)[1]
    assert "results.test_time DESC" in order_clause
    assert "results.id" in order_clause


def test_list_metric_monitor_events_bounds_by_suite_lookback(session_mock):
    """The suite's ``monitor_lookback`` (defaulting to 1) caps how many rows
    come back. The query baking the LIMIT directly via a CTE means the model
    doesn't need a second round-trip to read the lookback value."""
    session_mock.execute.return_value.mappings.return_value.all.return_value = []

    TestResult.list_metric_monitor_events(uuid4(), uuid4())

    raw_sql = str(session_mock.execute.call_args[0][0])
    assert "monitor_lookback" in raw_sql
    assert "lookback_multiplier" in raw_sql
