from unittest.mock import MagicMock, patch

import pytest

from testgen.commands.run_profiling import _order_largest_work_first, _run_column_profiling
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import WorkerOutcome

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_profiling"


def _col(table: str, column: str, record_ct: int = 10) -> ColumnChars:
    return ColumnChars(schema_name="s", table_name=table, column_name=column, record_ct=record_ct)


# --- _run_column_profiling: outcome-handling branches ------------------------------------

def _run_columns(outcomes: dict[str, tuple[str, object]]):
    """Drive _run_column_profiling with a stubbed worker pool.

    ``outcomes`` maps column_name -> ("ok", result_list) | ("err", message). The stubbed
    pool yields one WorkerOutcome per built work item, so the consumer loop under test runs
    its real branching over controlled results. Returns (profiling_run, ProfileResult mock,
    _write_column_error mock).
    """
    data_chars = [_col("t", name) for name in outcomes]
    sql_generator = MagicMock()
    sql_generator.run_column_profiling.return_value = ("SELECT 1", {})
    sql_generator.connection.max_threads = 4
    profiling_run = sql_generator.profiling_run

    def fake_pool(items, _process, *, max_threads):
        for column, _built in items:
            kind, payload = outcomes[column.column_name]
            if kind == "err":
                yield WorkerOutcome(key=column, result=None, error=payload)
            else:
                yield WorkerOutcome(key=column, result=payload, error=None)

    with (
        patch(f"{MODULE}.run_keyed_worker_pool", side_effect=fake_pool),
        patch(f"{MODULE}.get_current_session", return_value=MagicMock()),
        patch(f"{MODULE}.ProfileResult") as profile_result,
        patch(f"{MODULE}._write_column_error") as write_error,
    ):
        _run_column_profiling(sql_generator, data_chars, {}, {"t": 10})

    return profiling_run, profile_result, write_error


def _final_status(profiling_run: MagicMock) -> str:
    col_calls = [c for c in profiling_run.set_progress.call_args_list if c.args and c.args[0] == "col_profiling"]
    return col_calls[-1].args[1]


def test_all_columns_succeed_marks_completed():
    profiling_run, profile_result, write_error = _run_columns(
        {"c1": ("ok", [{"x": 1}]), "c2": ("ok", [{"x": 2}])}
    )
    assert _final_status(profiling_run) == "Completed"
    assert profile_result.upsert.call_count == 2
    write_error.assert_not_called()


def test_partial_failure_marks_warning_and_writes_error_row():
    profiling_run, profile_result, write_error = _run_columns(
        {"c1": ("ok", [{"x": 1}]), "c2": ("err", "boom")}
    )
    assert _final_status(profiling_run) == "Warning"
    assert profile_result.upsert.call_count == 1
    assert write_error.call_count == 1


def test_all_columns_failing_raises():
    with pytest.raises(RuntimeError):
        _run_columns({"c1": ("err", "boom"), "c2": ("err", "boom2")})


def test_empty_result_is_skipped_without_error():
    # Characterizes current behavior: a column whose query returns no rows writes nothing
    # and is not counted as an error, so the pass still completes.
    profiling_run, profile_result, write_error = _run_columns({"c1": ("ok", [])})
    assert _final_status(profiling_run) == "Completed"
    profile_result.upsert.assert_not_called()
    write_error.assert_not_called()


# --- _order_largest_work_first -----------------------------------------------------------

def test_orders_largest_table_first():
    columns = [_col("small", "c"), _col("big", "c"), _col("mid", "c")]
    ordered = _order_largest_work_first(columns, {"small": 1, "big": 100, "mid": 10})
    assert [c.table_name for c in ordered] == ["big", "mid", "small"]


def test_missing_record_count_sorts_as_zero():
    columns = [_col("known", "c"), _col("unknown", "c")]
    ordered = _order_largest_work_first(columns, {"known": 5})
    assert [c.table_name for c in ordered] == ["known", "unknown"]


def test_equal_counts_preserve_input_order():
    columns = [_col("a", "c"), _col("b", "c"), _col("d", "c")]
    ordered = _order_largest_work_first(columns, {"a": 5, "b": 5, "d": 5})
    assert [c.table_name for c in ordered] == ["a", "b", "d"]
