import hashlib
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import get_args
from unittest.mock import ANY, MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands.queries.profiling_query import TableSampling
from testgen.commands.run_profiling import (
    PROFILE_RESULT_SHAPE_VERSION,
    ProfilingJob,
    _order_largest_work_first,
    _profiling_template_digest,
    _write_frequency_error,
    report_profiling_run,
)
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import WorkerOutcome
from testgen.common.database.flavor.flavor_service import SQLFlavor
from testgen.common.database.profiling_capabilities import ProfilingCapabilities
from testgen.common.enums import JobKey, JobStatus
from testgen.common.models import get_current_session
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import PROGRESS_KEYS
from testgen.common.models.stg_functional_table_update import StgFunctionalTableUpdate
from testgen.common.pausable_job import PausableJob, Step, WorkTasksChanged

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_profiling"
POOL = "testgen.common.pausable_job.run_keyed_worker_pool"


def _col(table: str, column: str, record_ct: int = 10) -> ColumnChars:
    return ColumnChars(schema_name="s", table_name=table, column_name=column, record_ct=record_ct)


def _no_job_row_session() -> MagicMock:
    """A session with no job_executions row, so the engine sees a fresh run rather than
    reading a checkpoint off an auto-created mock attribute."""
    session = MagicMock()
    session.get.return_value = None
    return session


# --- the column profiling step: outcome-handling branches --------------------------------

def _run_columns(
    outcomes: dict[str, tuple[str, object]],
    sampling_params: dict[str, TableSampling] | None = None,
    capabilities: ProfilingCapabilities | None = None,
    sql_generator: MagicMock | None = None,
):
    """Drive the column profiling step through the engine with a stubbed worker pool.

    ``outcomes`` maps column_name -> ("ok", result_list) | ("err", message). The SQL generator
    supplies no row values unless ``sql_generator`` is given. Returns
    (profiling_run, ProfileResult mock, _write_column_error mock).
    """
    data_chars = [_col("t", name) for name in outcomes]

    job = ProfilingJob.__new__(ProfilingJob)
    PausableJob.__init__(job, job_id=uuid4())
    job.data_chars = data_chars
    job.table_record_counts = {"t": 10}
    job.sampling_params = sampling_params or {}
    job.capabilities = capabilities or ProfilingCapabilities()
    if sql_generator is None:
        sql_generator = MagicMock()
        sql_generator.profiled_row_values.return_value = {}
    job.sql_generator = sql_generator
    job.sql_generator.run_column_profiling.return_value = ("SELECT 1", {})
    job.connection = MagicMock(max_threads=4)
    job.profiling_run = MagicMock(**{"progress_error.return_value": None})
    job.STEPS = (Step("col_profiling", ProfilingJob._col_profiling),)

    def fake_pool(items, _process, *, max_threads, stop=None):
        for column, _built in items:
            kind, payload = outcomes[column.column_name]
            if kind == "err":
                yield WorkerOutcome(key=column, result=None, error=payload)
            else:
                yield WorkerOutcome(key=column, result=payload, error=None)

    # on_start derives the entities this helper supplies directly
    # and only exercises the column-profiling step, so they are no-ops here.
    with (
        patch(POOL, side_effect=fake_pool),
        patch(f"{MODULE}.get_current_session", return_value=MagicMock()),
        patch("testgen.common.pausable_job.get_current_session", return_value=_no_job_row_session()),
        patch(f"{MODULE}.with_frequent_patterns", side_effect=lambda row: row),
        patch.object(ProfilingJob, "on_start", lambda _self: None),
        patch(f"{MODULE}.ProfileResult") as profile_result,
        patch(f"{MODULE}._write_column_error") as write_error,
    ):
        job.execute()

    return job.profiling_run, profile_result, write_error


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
    profiling_run, profile_result, write_error = _run_columns({"c1": ("ok", [])})
    assert _final_status(profiling_run) == "Completed"
    profile_result.upsert.assert_not_called()
    write_error.assert_not_called()


SAMPLING = TableSampling(table_name="t", sample_count=3, sample_ratio=10 / 3, sample_percent=30.0)


@pytest.mark.parametrize("approx_percentile", [False, True])
def test_a_measured_row_is_written_with_the_values_the_run_supplies(approx_percentile):
    sql_generator = MagicMock()
    sql_generator.profiled_row_values.return_value = {"column_name": "c1", "percentile_method": "exact"}

    _, profile_result, _ = _run_columns(
        {"c1": ("ok", [{"record_ct": 3}])},
        capabilities=ProfilingCapabilities(approx_percentile=approx_percentile),
        sql_generator=sql_generator,
    )

    sql_generator.profiled_row_values.assert_called_once_with(_col("t", "c1"), approx_percentile)
    profile_result.upsert.assert_called_once_with({"record_ct": 3, "column_name": "c1", "percentile_method": "exact"})


def test_a_row_is_calibrated_before_it_is_written():
    _, profile_result, _ = _run_columns({"c1": ("ok", [{"record_ct": 3}])})

    profile_result.calibrate_sampled_counts.assert_called_once_with({"record_ct": 3})
    names = [name for name, _args, _kwargs in profile_result.mock_calls]
    assert names.index("calibrate_sampled_counts") < names.index("upsert")


def test_a_sampled_tables_row_records_the_ratio():
    _, profile_result, _ = _run_columns({"c1": ("ok", [{"record_ct": 3}])}, sampling_params={"t": SAMPLING})

    profile_result.upsert.assert_called_once_with({"record_ct": 3, "sample_ratio": SAMPLING.sample_ratio})


def test_a_table_that_is_not_sampled_records_no_ratio():
    other_table = TableSampling(table_name="u", sample_count=3, sample_ratio=10 / 3, sample_percent=30.0)
    _, profile_result, _ = _run_columns({"c1": ("ok", [{"record_ct": 3}])}, sampling_params={"u": other_table})

    profile_result.upsert.assert_called_once_with({"record_ct": 3})


def test_an_error_row_on_a_sampled_table_is_not_calibrated():
    # An error row carries the catalog's exact record count and nothing measured on the sample.
    _, profile_result, write_error = _run_columns({"c1": ("err", "boom"), "c2": ("ok", [{"x": 1}])}, sampling_params={"t": SAMPLING})

    assert profile_result.calibrate_sampled_counts.call_count == 1
    assert profile_result.calibrate_sampled_counts.call_args.args[0]["x"] == 1
    write_error.assert_called_once()
    assert write_error.call_args.args[1:] == (_col("t", "c1"), "boom")


# --- the frequency analysis step ---------------------------------------------------------

def _freq_job(tasks: list[str], completed: int) -> ProfilingJob:
    job = ProfilingJob.__new__(ProfilingJob)
    PausableJob.__init__(job, job_id=uuid4())
    job.data_chars = [_col("t", "c1")]
    job.table_record_counts = {"t": 10}
    job.sampling_params = {}
    job.sql_generator = MagicMock()
    job.connection = MagicMock(max_threads=4)
    job.profiling_run = MagicMock(**{"progress_error.return_value": None})
    job._tasks = list(tasks)
    job._completed = completed
    job._step = Step("freq_analysis", ProfilingJob._freq_analysis, fatal=False)
    return job


def test_a_frequency_error_records_only_the_error_on_the_columns_row():
    """The column pass measured this column; a frequency failure must not blank its measures."""
    sql_generator = MagicMock(max_error_length=2000)
    with patch(f"{MODULE}.ProfileResult") as profile_result:
        _write_frequency_error(sql_generator, _col("t", "c1"), "boom")

    row = profile_result.upsert.call_args[0][0]
    assert row["query_error"] == "boom"
    assert row["table_name"] == "t"
    assert row["column_name"] == "c1"
    assert not row.keys() & {"general_type", "position", "column_type", "db_data_type", "record_ct"}


def test_a_frequency_error_does_not_write_the_column_pass_error_row():
    outcomes = {"c1": ("err", "boom")}

    job = _freq_job(tasks=[], completed=0)
    job.STEPS = (Step("freq_analysis", ProfilingJob._freq_analysis, fatal=False),)

    def fake_pool(items, _process, *, max_threads, stop=None):
        for column, _built in items:
            _kind, payload = outcomes[column.column_name]
            yield WorkerOutcome(key=column, result=None, error=payload)

    with (
        patch(POOL, side_effect=fake_pool),
        patch(f"{MODULE}.fetch_dict_from_db", return_value=[MappingProxyType({"schema_name": "s", "table_name": "t", "column_name": "c1", "value_ct": 10})]),
        patch(f"{MODULE}.get_current_session", return_value=MagicMock()),
        patch("testgen.common.pausable_job.get_current_session", return_value=_no_job_row_session()),
        patch.object(ProfilingJob, "on_start", lambda _self: None),
        patch(f"{MODULE}._write_frequency_error") as write_frequency_error,
        patch(f"{MODULE}._write_column_error") as write_column_error,
    ):
        job.execute()

    write_frequency_error.assert_called_once()
    write_column_error.assert_not_called()


def _run_frequency(sampling_params: dict[str, TableSampling]) -> dict:
    rows = [
        {"value": "A", "value_ct": 6, "value_rank": 1, "other_distinct_ct": None, "sample_value_ct": 10,
         "distinct_value_hash": "h"},
        {"value": None, "value_ct": 3, "value_rank": 11, "other_distinct_ct": 4, "sample_value_ct": 10,
         "distinct_value_hash": "h"},
    ]
    job = _freq_job(tasks=[], completed=0)
    job.sampling_params = sampling_params
    job.STEPS = (Step("freq_analysis", ProfilingJob._freq_analysis, fatal=False),)

    def fake_pool(items, _process, *, max_threads, stop=None):
        for column, _built in items:
            yield WorkerOutcome(key=column, result=rows, error=None)

    with (
        patch(POOL, side_effect=fake_pool),
        patch(
            f"{MODULE}.fetch_dict_from_db",
            return_value=[MappingProxyType({"schema_name": "s", "table_name": "t", "column_name": "c1", "value_ct": 25})],
        ),
        patch(f"{MODULE}.get_current_session", return_value=MagicMock()),
        patch("testgen.common.pausable_job.get_current_session", return_value=_no_job_row_session()),
        patch.object(ProfilingJob, "on_start", lambda _self: None),
        patch.object(ProfileResult, "upsert") as upsert,
    ):
        job.execute()

    upsert.assert_called_once()
    return upsert.call_args.args[0]["frequent_values"]


def test_frequent_values_of_a_sampled_table_are_lifted_by_the_columns_value_count():
    assert _run_frequency({"t": SAMPLING}) == {
        "values": [{"value": "A", "ct": 15}],
        "other": {"distinct_ct": 4, "ct": 8},
    }


def test_frequent_values_of_a_table_that_is_not_sampled_are_written_as_counted():
    assert _run_frequency({}) == {"values": [{"value": "A", "ct": 6}], "other": {"distinct_ct": 4, "ct": 3}}


def test_losing_every_eligible_column_restarts_the_run():
    job = _freq_job(tasks=["freq_analysis\x1fs\x1ft\x1fc1"], completed=1)

    with patch(f"{MODULE}.fetch_dict_from_db", return_value=[]), pytest.raises(WorkTasksChanged):
        job._freq_analysis()


def test_nothing_eligible_on_a_fresh_run_is_not_drift():
    job = _freq_job(tasks=[], completed=0)

    with patch(f"{MODULE}.fetch_dict_from_db", return_value=[]):
        job._freq_analysis()

    assert job._tasks == []


# --- the step declaration ----------------------------------------------------------------

def test_steps_run_in_the_order_the_results_depend_on():
    assert [step.name for step in ProfilingJob.STEPS] == [
        "data_chars",
        "col_profiling",
        "freq_analysis",
        "hygiene_issues",
        "generate_tests",
    ]


def test_only_the_steps_everything_depends_on_are_fatal():
    fatal = {step.name for step in ProfilingJob.STEPS if step.fatal}
    assert fatal == {"data_chars", "col_profiling"}


def test_reporting_steps_match_the_progress_display():
    reported = {step.name for step in ProfilingJob.STEPS if step.name in PROGRESS_KEYS}
    assert reported == {"data_chars", "col_profiling", "freq_analysis", "hygiene_issues"}


def test_a_column_is_identified_by_where_it_lives():
    job = ProfilingJob.__new__(ProfilingJob)
    assert job.canonical_key(_col("t", "c")) == "s\x1ft\x1fc"


# --- _order_largest_work_first -----------------------------------------------------------

def test_orders_largest_table_first():
    columns = [_col("small", "c"), _col("big", "c"), _col("mid", "c")]
    ordered = _order_largest_work_first(columns, {"small": 1, "big": 100, "mid": 10})
    assert [c.table_name for c in ordered] == ["big", "mid", "small"]


def test_missing_record_count_sorts_as_zero():
    columns = [_col("known", "c"), _col("unknown", "c")]
    ordered = _order_largest_work_first(columns, {"known": 5})
    assert [c.table_name for c in ordered] == ["known", "unknown"]


def test_equal_counts_are_broken_by_name_not_by_input_order():
    """Input order is no tie-break: the queries these columns come from do not all sort their
    rows, and a resume that regenerates them in a different sequence must still match."""
    columns = [_col("d", "c"), _col("a", "c"), _col("b", "c")]
    ordered = _order_largest_work_first(columns, {"a": 5, "b": 5, "d": 5})
    assert [c.table_name for c in ordered] == ["a", "b", "d"]


def test_the_order_is_the_same_whatever_order_the_columns_arrive_in():
    counts = {"big": 100, "small": 1}
    columns = [_col("big", "y"), _col("small", "b"), _col("big", "x"), _col("small", "a")]
    def key(cols):
        return [(c.table_name, c.column_name) for c in _order_largest_work_first(cols, counts)]

    assert key(columns) == key(list(reversed(columns)))
    # Largest table first is still the point; names only settle ties.
    assert key(columns) == [("big", "x"), ("big", "y"), ("small", "a"), ("small", "b")]


# --- generation is enqueued as follow-up jobs, not run in-process -------------------------

SUITE_ID = "8f8d1cb5-2f2c-4f0f-9f9c-6f1a2b3c4d5e"
MONITOR_SUITE_ID = "9a9e2dc6-3030-4a1a-8080-7c2b3c4d5e6f"


def _enqueue(*, default_test_suite_id=SUITE_ID, monitor_test_suite_id=None, last_complete_profile_run_id=None):
    job = ProfilingJob.__new__(ProfilingJob)
    job.profiling_run = MagicMock(id=uuid4())
    job.table_group = MagicMock(
        default_test_suite_id=default_test_suite_id,
        monitor_test_suite_id=monitor_test_suite_id,
        last_complete_profile_run_id=last_complete_profile_run_id,
        project_code="DEFAULT",
    )
    with (
        patch(f"{MODULE}.TestSuite") as test_suite,
        patch(f"{MODULE}.JobExecution") as job_execution,
    ):
        test_suite.get.return_value = MagicMock(monitor_regenerate_freshness=False)
        job._enqueue_generation()
    return job_execution.submit


def _submitted_keys(submit_mock):
    return [c.kwargs["job_key"] for c in submit_mock.call_args_list]


def test_first_run_enqueues_both_monitor_and_test_generation():
    submit = _enqueue(monitor_test_suite_id=MONITOR_SUITE_ID)
    keys = _submitted_keys(submit)
    assert JobKey.run_monitor_generation in keys
    assert JobKey.run_test_generation in keys
    monitor_call = next(c for c in submit.call_args_list if c.kwargs["job_key"] == JobKey.run_monitor_generation)
    assert monitor_call.kwargs["kwargs"]["mode"] == "upsert"


def test_later_run_enqueues_monitor_only_and_in_insert_mode():
    submit = _enqueue(monitor_test_suite_id=MONITOR_SUITE_ID, last_complete_profile_run_id="a-previous-run")
    keys = _submitted_keys(submit)
    assert keys == [JobKey.run_monitor_generation]  # no standard test generation after the first run
    assert submit.call_args_list[0].kwargs["kwargs"]["mode"] == "insert"


def test_no_monitor_suite_enqueues_no_monitor_generation():
    submit = _enqueue(monitor_test_suite_id=None)
    assert JobKey.run_monitor_generation not in _submitted_keys(submit)


def test_no_default_suite_enqueues_no_test_generation():
    submit = _enqueue(default_test_suite_id=None, monitor_test_suite_id=MONITOR_SUITE_ID)
    assert JobKey.run_test_generation not in _submitted_keys(submit)


# --- lifecycle: inert __init__, on_start derives, on_restart clears ----------------------

ORIGINAL_START = datetime(2020, 1, 1, tzinfo=UTC)


def test_constructing_the_job_reads_nothing_and_writes_nothing():
    """The constructor records inputs only; entity loads and the run row belong to on_start."""
    with (
        patch(f"{MODULE}.job_context") as job_ctx,
        patch(f"{MODULE}.TableGroup") as table_group,
        patch(f"{MODULE}.Connection") as connection,
        patch(f"{MODULE}.set_target_db_params") as set_params,
        patch(f"{MODULE}.get_current_session") as session,
    ):
        job_ctx.get.return_value = MagicMock(job_id=uuid4())
        job = ProfilingJob("tg-id", username="someone")

    assert job.table_group_id == "tg-id"
    assert job.table_group is None and job.connection is None and job.profiling_run is None
    table_group.get.assert_not_called()
    connection.get.assert_not_called()
    set_params.assert_not_called()
    session.assert_not_called()


def test_a_job_with_no_context_is_refused():
    with patch(f"{MODULE}.job_context") as job_ctx:
        job_ctx.get.return_value = MagicMock(job_id=None)
        with pytest.raises(ValueError, match="must run as a job"):
            ProfilingJob("tg-id")


def _started_job(existing_run=None):
    with (
        patch(f"{MODULE}.job_context") as job_ctx,
        patch(f"{MODULE}.TableGroup") as table_group,
        patch(f"{MODULE}.Connection"),
        patch(f"{MODULE}.ProfilingRun") as profiling_run_cls,
        patch(f"{MODULE}.ProfilingSQL") as sql_generator_cls,
        patch(f"{MODULE}.set_target_db_params") as set_params,
        patch(f"{MODULE}.get_current_session"),
    ):
        job_ctx.get.return_value = MagicMock(job_id=uuid4())
        profiling_run_cls.get.return_value = existing_run
        job = ProfilingJob("tg-id")
        job.on_start()
        return job, table_group, profiling_run_cls, sql_generator_cls, set_params


def test_on_start_derives_the_entities_and_creates_a_fresh_run():
    job, table_group, profiling_run_cls, sql_generator_cls, set_params = _started_job(existing_run=None)
    table_group.get.assert_called_once_with("tg-id")
    set_params.assert_called_once_with(ANY, table_group.get.return_value)
    assert job.profiling_run is profiling_run_cls.return_value  # constructed, since get returned None
    assert job.sql_generator is sql_generator_cls.return_value


def test_on_start_reuses_an_existing_run_row_on_resume():
    existing = MagicMock()
    job, _, profiling_run_cls, _, _ = _started_job(existing_run=existing)
    assert job.profiling_run is existing
    profiling_run_cls.assert_not_called()  # did not construct a second row
    existing.init_progress.assert_called_once()


def test_on_start_keeps_a_resumed_runs_original_start_time():
    """A resume continues the same run, so its start time anchors the whole run and not the
    attempt that picked it back up -- otherwise the recorded duration loses the paused span."""
    existing = MagicMock()
    existing.profiling_starttime = ORIGINAL_START

    _started_job(existing_run=existing)

    assert existing.profiling_starttime == ORIGINAL_START


def _settled_job_exec(active_seconds=None, started_at=None, completed_at=None, status=JobStatus.COMPLETED):
    job_exec = MagicMock()
    job_exec.id = uuid4()
    job_exec.source = "ui"
    job_exec.kwargs = {}
    job_exec.active_seconds = active_seconds
    job_exec.started_at = started_at
    job_exec.completed_at = completed_at
    job_exec.status = status
    return job_exec


def test_the_report_uses_the_accumulated_active_time():
    """The point of the accumulator: a run that stopped and continued spans more wall-clock
    time than it worked, so the elapsed span between its start and end overstates it."""
    started = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    completed = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)  # an hour of wall clock
    job_exec = _settled_job_exec(active_seconds=90.0, started_at=started, completed_at=completed)

    with (
        patch(f"{MODULE}.ProfilingRun"),
        patch(f"{MODULE}.TableGroup"),
        patch(f"{MODULE}.Connection"),
        patch(f"{MODULE}.MixpanelService") as mixpanel,
    ):
        report_profiling_run(job_exec)

    assert mixpanel.return_value.send_event.call_args.kwargs["run_duration"] == 90.0


def test_the_report_sends_no_duration_for_a_run_that_never_worked():
    """The accumulated total is the only answer now, and a backfill gave one to every run that
    had already finished -- so a missing total means the run never worked, not that the span
    has to be computed instead."""
    completed = datetime(2026, 1, 1, 10, 2, tzinfo=UTC)
    job_exec = _settled_job_exec(active_seconds=None, completed_at=completed)

    with (
        patch(f"{MODULE}.ProfilingRun"),
        patch(f"{MODULE}.TableGroup"),
        patch(f"{MODULE}.Connection"),
        patch(f"{MODULE}.MixpanelService") as mixpanel,
    ):
        report_profiling_run(job_exec)

    assert mixpanel.return_value.send_event.call_args.kwargs["run_duration"] is None


def test_the_report_runs_inside_a_session_it_opened_itself(db_session_mock):
    """Final callbacks fire outside the transaction that settled the run, so a callback that
    reaches for entities has to open one itself. Without a session it raises into a caller that
    swallows the error, losing the event instead of reporting the failure.

    Asserts the session is live rather than waiting for a raise: with the entities patched
    nothing touches the session, which is exactly why patching them hid this."""
    job_exec = _settled_job_exec(active_seconds=5.0)
    session_during_send = []

    with (
        patch(f"{MODULE}.ProfilingRun"),
        patch(f"{MODULE}.TableGroup"),
        patch(f"{MODULE}.Connection"),
        patch(f"{MODULE}.MixpanelService") as mixpanel,
    ):
        mixpanel.return_value.send_event.side_effect = (
            lambda *_a, **_k: session_during_send.append(get_current_session())
        )
        report_profiling_run(job_exec)

    assert session_during_send, "the event was never sent"
    assert session_during_send[0] is not None


def test_the_report_is_skipped_when_the_run_never_got_a_row():
    """A failure before the run row is written leaves nothing to report on, and reaching for
    its table group would raise inside a best-effort callback that swallows the error."""
    job_exec = _settled_job_exec()

    with (
        patch(f"{MODULE}.ProfilingRun") as profiling_run,
        patch(f"{MODULE}.MixpanelService") as mixpanel,
    ):
        profiling_run.get.return_value = None
        report_profiling_run(job_exec)

    mixpanel.return_value.send_event.assert_not_called()


def test_on_restart_clears_the_abandoned_run_and_resets_the_start_time():
    """The zero-coverage path where the misplaced delete_for_run hid in build-step 1."""
    job = ProfilingJob.__new__(ProfilingJob)
    job.time_delta = timedelta()
    job.profiling_run = MagicMock()
    job.profiling_run.profiling_starttime = ORIGINAL_START
    with (
        patch(f"{MODULE}.ProfileResult") as profile_result,
        patch(f"{MODULE}.HygieneIssue") as hygiene_issue,
        patch(f"{MODULE}.StgFunctionalTableUpdate") as staged_tables,
        patch(f"{MODULE}.get_current_session"),
    ):
        profile_result.delete_for_run.return_value = 5
        job.on_restart()
        profile_result.delete_for_run.assert_called_once_with(job.profiling_run.id)
        hygiene_issue.delete_for_run.assert_called_once_with(job.profiling_run.id)
        staged_tables.delete_for_run.assert_called_once_with(job.profiling_run.id)
    # Restamped, not merely assigned: a restart is a new run and its duration starts here.
    assert job.profiling_run.profiling_starttime > ORIGINAL_START


def test_the_cleanup_methods_exist_on_the_models_on_restart_calls():
    """Guards the exact build-step-1 bug: delete_for_run landed on HygieneIssueType, not
    HygieneIssue, so on_restart raised AttributeError only at runtime."""
    assert hasattr(HygieneIssue, "delete_for_run")
    assert hasattr(ProfileResult, "delete_for_run")
    assert hasattr(StgFunctionalTableUpdate, "delete_for_run")


# --- the measurement fence: a resume must not mix two builds' readings --------------------

def test_the_template_digest_resolves_for_every_flavor():
    """A flavor whose profiling templates cannot be located would fail the fence at runtime,
    on that flavor only.

    An empty template directory still hashes, so the digest of no input is rejected explicitly —
    otherwise a flavor with a directory but no templates passes.
    """
    digest_of_nothing = hashlib.sha256().hexdigest()
    for flavor in get_args(SQLFlavor):
        digest = _profiling_template_digest(flavor)
        assert len(digest) == 64
        assert digest != digest_of_nothing, f"{flavor} has no profiling templates"


def test_the_template_digest_tracks_content_and_names():
    def digest(text: str, name: str = "project_profiling_query.sql"):
        entry = MagicMock(**{"read_text.return_value": text})
        entry.name = name  # `name` is reserved in the MagicMock constructor
        with patch(f"{MODULE}.get_template_files", return_value=[entry]):
            return _profiling_template_digest("snowflake")

    baseline = digest("SELECT 1")
    assert digest("SELECT 1") == baseline
    assert digest("SELECT 2") != baseline
    assert digest("SELECT 1", name="renamed.sql") != baseline


def test_data_chars_pins_the_result_shape_and_the_templates():
    job = ProfilingJob.__new__(ProfilingJob)
    PausableJob.__init__(job, job_id=uuid4())
    job.table_group = MagicMock(profile_exclude_xde=False)
    job.profiling_run = MagicMock()
    job.sql_generator = MagicMock(flavor="snowflake")
    job.data_chars = []

    with (
        patch.object(ProfilingJob, "once", return_value=False),
        patch(f"{MODULE}.DataTable") as data_table,
        # Capability resolution probes the target database.
        patch(
            f"{MODULE}.resolve_profiling_capabilities", return_value=ProfilingCapabilities(approx_percentile=True)
        ) as resolve,
    ):
        data_table.list_column_chars.return_value = []
        job._data_chars()

    resolve.assert_called_once_with(job.sql_generator.flavor_service)
    assert job.capabilities == ProfilingCapabilities(approx_percentile=True)
    assert job._pins["result_shape"] == PROFILE_RESULT_SHAPE_VERSION
    assert job._pins["profiling_templates"] == _profiling_template_digest("snowflake")
    # A probe that answers differently after a pause would file two readings of one measure.
    assert job._pins["approx_percentile"] is True


@pytest.mark.parametrize("approx_percentile", [False, True])
def test_the_column_query_is_built_with_the_resolved_percentile_method(approx_percentile):
    job = ProfilingJob.__new__(ProfilingJob)
    PausableJob.__init__(job, job_id=uuid4())
    job.sampling_params = {}
    job.capabilities = ProfilingCapabilities(approx_percentile=approx_percentile)
    job.sql_generator = MagicMock()

    job._build_column_query(_col("t", "c"))

    job.sql_generator.run_column_profiling.assert_called_once_with(
        _col("t", "c"), None, use_approx_percentile=approx_percentile
    )


def test_a_checkpoint_from_a_build_that_measured_differently_is_discarded():
    """The fence rides pin(), so a drifted value restarts the run rather than extending it."""
    job = ProfilingJob.__new__(ProfilingJob)
    PausableJob.__init__(job, job_id=uuid4())
    job._pins = {"result_shape": PROFILE_RESULT_SHAPE_VERSION + 1}

    with pytest.raises(WorkTasksChanged):
        job.pin("result_shape", PROFILE_RESULT_SHAPE_VERSION)


@pytest.mark.parametrize("status", [JobStatus.CANCELED, JobStatus.CANCEL_REQUESTED])
def test_a_canceled_run_is_not_reported(status):
    """It settles through these same callbacks, but its counts describe work somebody abandoned
    partway rather than a run that produced results."""
    job_exec = _settled_job_exec(active_seconds=90.0, status=status)

    with (
        patch(f"{MODULE}.ProfilingRun"),
        patch(f"{MODULE}.TableGroup"),
        patch(f"{MODULE}.Connection"),
        patch(f"{MODULE}.MixpanelService") as mixpanel,
    ):
        report_profiling_run(job_exec)

    mixpanel.return_value.send_event.assert_not_called()


def test_a_run_that_errored_is_still_reported():
    """It ran and measured what it could; only a cancel is excluded."""
    job_exec = _settled_job_exec(active_seconds=90.0, status=JobStatus.ERROR)

    with (
        patch(f"{MODULE}.ProfilingRun"),
        patch(f"{MODULE}.TableGroup"),
        patch(f"{MODULE}.Connection"),
        patch(f"{MODULE}.MixpanelService") as mixpanel,
    ):
        report_profiling_run(job_exec)

    mixpanel.return_value.send_event.assert_called_once()
