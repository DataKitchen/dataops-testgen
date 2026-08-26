from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.commands.run_data_cleanup import BATCH_SIZE, run_data_cleanup

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_data_cleanup"


def _db_ctx():
    """Mock database_session() that yields nothing useful — the orchestrator's
    nested with-blocks just need the context manager to enter/exit cleanly."""
    ctx = MagicMock()
    ctx.__enter__ = Mock(return_value=MagicMock())
    ctx.__exit__ = Mock(return_value=False)
    return ctx


def _patch_orchestrator(
    protected_profiling: set | None = None,
    protected_tests: set | None = None,
    protected_profiling_jes: set | None = None,
    protected_test_jes: set | None = None,
    protected_history_keys: set | None = None,
    deleted_profiling: int = 0,
    deleted_tests: int = 0,
    deleted_job_executions: int = 0,
    deleted_score_history: int = 0,
    deleted_score_latest: int = 0,
    deleted_stg: tuple[int, int, int] = (0, 0, 0),
):
    """One-stop helper: patches every collaborator the orchestrator touches.

    Returns a dict of the patch mocks so individual tests can assert call shape.
    """
    patches = {
        "database_session": patch(f"{MODULE}.database_session", side_effect=lambda: _db_ctx()),
        "ProfilingRun": patch(f"{MODULE}.ProfilingRun"),
        "TestRun": patch(f"{MODULE}.TestRun"),
        "JobExecution": patch(f"{MODULE}.JobExecution"),
        "ScoreHistoryLatestRun": patch(f"{MODULE}.ScoreHistoryLatestRun"),
        "ScoreDefinitionResultHistoryEntry": patch(f"{MODULE}.ScoreDefinitionResultHistoryEntry"),
        "StgFunctionalTableUpdate": patch(f"{MODULE}.StgFunctionalTableUpdate"),
        "StgDataCharsUpdate": patch(f"{MODULE}.StgDataCharsUpdate"),
        "StgTestDefinitionUpdate": patch(f"{MODULE}.StgTestDefinitionUpdate"),
    }
    started = {name: p.start() for name, p in patches.items()}

    # The run id IS the job execution id, so find_latest_* returns the protected
    # JE ids directly. The *_jes params let a test name the same set as JE ids.
    started["ProfilingRun"].find_latest_per_table_group.return_value = (
        protected_profiling_jes or protected_profiling or set()
    )
    started["ProfilingRun"].delete_older_than.return_value = deleted_profiling

    started["TestRun"].find_latest_per_test_suite.return_value = (
        protected_test_jes or protected_tests or set()
    )
    started["TestRun"].delete_older_than.return_value = deleted_tests

    started["JobExecution"].delete_older_than.return_value = deleted_job_executions

    started["ScoreHistoryLatestRun"].find_protected_keys.return_value = protected_history_keys or set()
    started["ScoreHistoryLatestRun"].delete_older_than.return_value = deleted_score_latest
    started["ScoreDefinitionResultHistoryEntry"].delete_older_than.return_value = deleted_score_history

    started["StgFunctionalTableUpdate"].delete_older_than.return_value = deleted_stg[0]
    started["StgDataCharsUpdate"].delete_older_than.return_value = deleted_stg[1]
    started["StgTestDefinitionUpdate"].delete_older_than.return_value = deleted_stg[2]

    return started, patches


def _stop(patches):
    for p in patches.values():
        p.stop()


def test_computes_cutoff_from_retention_days():
    """Cutoff passed to delete_older_than is `now - retention_days` (UTC)."""
    started, patches = _patch_orchestrator()
    try:
        before = datetime.now(UTC)
        run_data_cleanup(project_code="proj", retention_days=30)
        after = datetime.now(UTC)
    finally:
        _stop(patches)

    cutoff = started["ProfilingRun"].delete_older_than.call_args.kwargs["cutoff"]
    expected_low = before - timedelta(days=30)
    expected_high = after - timedelta(days=30)
    assert expected_low <= cutoff <= expected_high
    # Same cutoff threads through every sweep
    assert started["TestRun"].delete_older_than.call_args.kwargs["cutoff"] == cutoff
    assert started["JobExecution"].delete_older_than.call_args.kwargs["cutoff"] == cutoff


def test_passes_protected_profiling_ids_to_delete():
    """Latest-run-per-table-group set is computed once and threaded through to
    ProfilingRun.delete_older_than as the carve-out."""
    protected = {uuid4(), uuid4(), uuid4()}
    started, patches = _patch_orchestrator(protected_profiling=protected)
    try:
        run_data_cleanup(project_code="proj", retention_days=180)
    finally:
        _stop(patches)

    started["ProfilingRun"].find_latest_per_table_group.assert_called_once_with("proj")
    assert started["ProfilingRun"].delete_older_than.call_args.kwargs["protected_ids"] == protected


def test_passes_protected_test_run_ids_to_delete():
    """Latest-run-per-test-suite (incl. monitor suites) threads through to TestRun.delete_older_than."""
    protected = {uuid4(), uuid4()}
    started, patches = _patch_orchestrator(protected_tests=protected)
    try:
        run_data_cleanup(project_code="proj", retention_days=180)
    finally:
        _stop(patches)

    started["TestRun"].find_latest_per_test_suite.assert_called_once_with("proj")
    assert started["TestRun"].delete_older_than.call_args.kwargs["protected_ids"] == protected


def test_protected_job_execution_ids_is_union_of_run_je_ids():
    """JobExecution sweep carve-out = union of protected profiling + test run JE ids."""
    profiling_jes = {uuid4(), uuid4()}
    test_jes = {uuid4()}
    started, patches = _patch_orchestrator(
        protected_profiling_jes=profiling_jes,
        protected_test_jes=test_jes,
    )
    try:
        run_data_cleanup(project_code="proj", retention_days=180)
    finally:
        _stop(patches)

    passed = started["JobExecution"].delete_older_than.call_args.kwargs["protected_ids"]
    assert passed == profiling_jes | test_jes


def test_score_history_uses_protected_keys_from_latest_runs():
    """find_protected_keys runs once with both run-id sets, and its result feeds
    BOTH score-history sweeps (history entries + latest-runs mapping)."""
    keys = {(uuid4(), datetime(2026, 1, 1)), (uuid4(), datetime(2026, 2, 1))}
    profiling_ids = {uuid4()}
    test_ids = {uuid4()}
    started, patches = _patch_orchestrator(
        protected_profiling=profiling_ids,
        protected_tests=test_ids,
        protected_history_keys=keys,
    )
    try:
        run_data_cleanup(project_code="proj", retention_days=180)
    finally:
        _stop(patches)

    started["ScoreHistoryLatestRun"].find_protected_keys.assert_called_once_with(
        protected_profiling_ids=profiling_ids,
        protected_test_run_ids=test_ids,
    )
    assert started["ScoreDefinitionResultHistoryEntry"].delete_older_than.call_args.kwargs["protected_keys"] == keys
    assert started["ScoreHistoryLatestRun"].delete_older_than.call_args.kwargs["protected_keys"] == keys


def test_staging_sweeps_get_no_carve_out():
    """All staging models receive only cutoff + project_code — no protected_ids
    arg (each run deletes its own staged rows, so the sweep only ever sees orphans)."""
    started, patches = _patch_orchestrator()
    try:
        run_data_cleanup(project_code="proj", retention_days=180)
    finally:
        _stop(patches)

    for stg_name in [
        "StgFunctionalTableUpdate",
        "StgDataCharsUpdate",
        "StgTestDefinitionUpdate",
    ]:
        call = started[stg_name].delete_older_than.call_args
        # Positional args only: (cutoff, project_code)
        assert len(call.args) == 2
        assert call.args[1] == "proj"
        assert "protected_ids" not in call.kwargs
        assert "protected_keys" not in call.kwargs


def test_batch_size_threaded_through():
    """The orchestrator's BATCH_SIZE constant is passed to every batch-capable sweep."""
    started, patches = _patch_orchestrator()
    try:
        run_data_cleanup(project_code="proj", retention_days=180)
    finally:
        _stop(patches)

    for collaborator, method in [
        ("ProfilingRun", "delete_older_than"),
        ("TestRun", "delete_older_than"),
        ("JobExecution", "delete_older_than"),
        ("ScoreDefinitionResultHistoryEntry", "delete_older_than"),
        ("ScoreHistoryLatestRun", "delete_older_than"),
    ]:
        kwargs = getattr(started[collaborator], method).call_args.kwargs
        assert kwargs["batch_size"] == BATCH_SIZE, f"{collaborator}.{method} missing batch_size"


def test_summary_log_has_all_counts(caplog):
    """The trailing summary log line includes the count from every sweep so the
    operator can correlate what was deleted in a single grep."""
    import logging
    caplog.set_level(logging.INFO, logger="testgen")

    started, patches = _patch_orchestrator(
        deleted_profiling=10,
        deleted_tests=20,
        deleted_job_executions=30,
        deleted_score_history=40,
        deleted_score_latest=50,
        deleted_stg=(2, 3, 4),  # sums to 9
    )
    try:
        run_data_cleanup(project_code="proj", retention_days=180)
    finally:
        _stop(patches)

    summary = [r for r in caplog.records if "Data retention cleanup complete" in r.getMessage()]
    assert len(summary) == 1
    msg = summary[0].getMessage()
    assert "deleted_profiling=10" in msg
    assert "deleted_tests=20" in msg
    assert "deleted_job_executions=30" in msg
    assert "deleted_score_history=40" in msg
    assert "deleted_score_latest=50" in msg
    assert "deleted_staging=9" in msg  # sum of staging counts


def test_no_data_to_delete_runs_clean():
    """Empty everywhere: handler completes without error, all sweeps still invoked."""
    started, patches = _patch_orchestrator()
    try:
        run_data_cleanup(project_code="proj", retention_days=180)
    finally:
        _stop(patches)

    # Every sweep was still called (cleanup is unconditional once the schedule fires)
    started["ProfilingRun"].delete_older_than.assert_called_once()
    started["TestRun"].delete_older_than.assert_called_once()
    started["JobExecution"].delete_older_than.assert_called_once()
    started["ScoreDefinitionResultHistoryEntry"].delete_older_than.assert_called_once()
    started["ScoreHistoryLatestRun"].delete_older_than.assert_called_once()
    for stg in [
        "StgFunctionalTableUpdate",
        "StgDataCharsUpdate",
        "StgTestDefinitionUpdate",
    ]:
        started[stg].delete_older_than.assert_called_once()
