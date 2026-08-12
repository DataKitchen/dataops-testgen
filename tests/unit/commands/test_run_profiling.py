from unittest.mock import MagicMock, Mock, patch
from uuid import UUID

import pytest

from testgen.commands.run_profiling import _generate_tests, _order_largest_work_first, _run_column_profiling
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


# --- _generate_tests: post-profiling auto-generation --------------------------------------

SUITE_ID = "8f8d1cb5-2f2c-4f0f-9f9c-6f1a2b3c4d5e"
PROFILE_RUN_ID = UUID("1c2d3e4f-5a6b-7c8d-9e0f-1a2b3c4d5e6f")


def _run_generate_tests(
    *,
    default_test_suite_id: str | None = SUITE_ID,
    last_complete_profile_run_id: str | None = None,
    monitor_test_suite_id: str | None = None,
    generation_error: Exception | None = None,
):
    table_group = MagicMock()
    table_group.default_test_suite_id = default_test_suite_id
    table_group.last_complete_profile_run_id = last_complete_profile_run_id
    table_group.monitor_test_suite_id = monitor_test_suite_id

    def db_ctx():
        ctx = MagicMock()
        ctx.__enter__ = Mock(return_value=MagicMock())
        ctx.__exit__ = Mock(return_value=False)
        return ctx

    with (
        patch("testgen.common.models.database_session", side_effect=lambda: db_ctx()),
        patch(f"{MODULE}.TestSuite"),
        patch(f"{MODULE}.run_monitor_generation"),
        patch(f"{MODULE}.run_test_generation", side_effect=generation_error) as run_generation,
    ):
        _generate_tests(table_group, PROFILE_RUN_ID)

    return run_generation


def test_post_profiling_generation_leaves_the_generation_sets_to_the_test_suite():
    """No generation set is passed, so run_test_generation resolves the suite's stored sets.

    Passing a set here would pin every post-profiling run to it regardless of what the
    suite was last generated with.
    """
    run_generation = _run_generate_tests()

    run_generation.assert_called_once_with(SUITE_ID, profile_run_id=PROFILE_RUN_ID)
    assert "generation_sets" not in run_generation.call_args.kwargs


def test_post_profiling_generation_only_runs_on_the_first_profile_run():
    run_generation = _run_generate_tests(last_complete_profile_run_id="a-previous-run")

    run_generation.assert_not_called()


def test_post_profiling_generation_skipped_without_a_default_test_suite():
    run_generation = _run_generate_tests(default_test_suite_id=None)

    run_generation.assert_not_called()


def test_post_profiling_generation_failure_does_not_fail_profiling():
    run_generation = _run_generate_tests(generation_error=RuntimeError("no generation sets"))

    run_generation.assert_called_once_with(SUITE_ID, profile_run_id=PROFILE_RUN_ID)
