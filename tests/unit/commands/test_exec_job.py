import inspect
import signal
import subprocess
import sys
import textwrap
import time
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.commands.exec_job import exec_job
from testgen.commands.job_registry import (
    JOB_DISPATCH,
    JOB_FINAL_CALLBACKS,
    JobConfig,
    run_final_callbacks,
)
from testgen.commands.run_test_execution import run_test_execution
from testgen.common.enums import PAUSABLE_JOB_KEYS, JobKey
from testgen.common.models.job_execution import JobExecution
from testgen.common.pausable_job import JobParked, PausableJob

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    with patch("testgen.common.models.Session", return_value=session):
        yield session


def _make_job_exec(job_key=JobKey.run_tests, status="claimed", **kwargs):
    job = MagicMock(spec=JobExecution)
    job.id = uuid4()
    job.job_key = job_key
    job.kwargs = {"test_suite_id": "suite-123"}
    job.source = "api"
    job.status = status
    job.configure_mock(**kwargs)
    return job


def test_exec_job_dispatches_run_tests(mock_session):
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = True
    dispatch_mock = Mock(return_value="ok")

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=dispatch_mock)}),
    ):
        exec_job(job.id)

    job.mark_running.assert_called_once()
    dispatch_mock.assert_called_once_with(**job.kwargs)
    job.mark_completed.assert_called_once()


def test_exec_job_dispatches_run_profile(mock_session):
    job = _make_job_exec(job_key=JobKey.run_profile)
    job.kwargs = {"table_group_id": "tg-123"}
    job.mark_running.return_value = True
    dispatch_mock = Mock(return_value="ok")

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_profile: JobConfig(handler=dispatch_mock)}),
    ):
        exec_job(job.id)

    dispatch_mock.assert_called_once_with(**job.kwargs)
    job.mark_completed.assert_called_once()


def test_exec_job_dispatches_run_monitors(mock_session):
    job = _make_job_exec(job_key=JobKey.run_monitors)
    job.mark_running.return_value = True
    dispatch_mock = Mock(return_value="ok")

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_monitors: JobConfig(handler=dispatch_mock)}),
    ):
        exec_job(job.id)

    dispatch_mock.assert_called_once_with(**job.kwargs)


def test_exec_job_dispatches_run_test_generation(mock_session):
    job = _make_job_exec(job_key=JobKey.run_test_generation)
    job.kwargs = {"test_suite_id": "suite-123", "generation_sets": ["Standard"]}
    job.mark_running.return_value = True
    dispatch_mock = Mock(return_value="ok")

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_test_generation: JobConfig(handler=dispatch_mock)}),
    ):
        exec_job(job.id)

    dispatch_mock.assert_called_once_with(**job.kwargs)


def test_exec_job_marks_interrupted_on_unknown_key(mock_session):
    job = _make_job_exec(job_key="nonexistent")

    with patch.object(JobExecution, "get", return_value=job):
        exec_job(job.id)

    job.mark_failed.assert_called_once()
    assert "Unknown job key" in job.mark_failed.call_args[0][0]
    job.mark_running.assert_not_called()


def test_exec_job_skips_when_mark_running_fails(mock_session):
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = False

    with patch.object(JobExecution, "get", return_value=job):
        exec_job(job.id)

    job.mark_completed.assert_not_called()


def test_exec_job_marks_interrupted_on_dispatch_error(mock_session):
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = True

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock(side_effect=RuntimeError("boom")))}),
    ):
        exec_job(job.id)

    job.mark_failed.assert_called_once()
    assert "boom" in job.mark_failed.call_args[0][0]
    job.mark_completed.assert_not_called()


def test_exec_job_exits_on_missing_record(mock_session):
    with (
        patch.object(JobExecution, "get", return_value=None),
        pytest.raises(SystemExit, match="1"),
    ):
        exec_job(uuid4())


def test_job_dispatch_has_all_job_keys():
    assert JobKey.run_profile in JOB_DISPATCH
    assert JobKey.run_tests in JOB_DISPATCH
    assert JobKey.run_monitors in JOB_DISPATCH
    assert JobKey.run_test_generation in JOB_DISPATCH
    assert JobKey.run_monitor_generation in JOB_DISPATCH
    assert JobKey.run_score_update in JOB_DISPATCH
    assert JobKey.recalculate_project_scores in JOB_DISPATCH


def test_exec_job_fires_final_callbacks_on_success(mock_session):
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = True
    job.mark_completed.return_value = True
    cb1, cb2 = Mock(), Mock()

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock(return_value="ok"))}),
        patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [cb1, cb2]}),
    ):
        exec_job(job.id)

    cb1.assert_called_once_with(job)
    cb2.assert_called_once_with(job)


def test_exec_job_runs_callbacks_in_registered_order(mock_session):
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = True
    job.mark_completed.return_value = True
    order = []
    cb1 = Mock(side_effect=lambda _: order.append("cb1"))
    cb2 = Mock(side_effect=lambda _: order.append("cb2"))

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock(return_value="ok"))}),
        patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [cb1, cb2]}),
    ):
        exec_job(job.id)

    assert order == ["cb1", "cb2"]


def test_exec_job_skips_callbacks_when_mark_completed_fails(mock_session):
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = True
    job.mark_completed.return_value = False
    cb = Mock()

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock(return_value="ok"))}),
        patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [cb]}),
    ):
        exec_job(job.id)

    cb.assert_not_called()


def test_exec_job_fires_callbacks_on_interrupted(mock_session):
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = True
    job.mark_failed.return_value = True
    cb = Mock()

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock(side_effect=RuntimeError("boom")))}),
        patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [cb]}),
    ):
        exec_job(job.id)

    cb.assert_called_once_with(job)


def test_exec_job_skips_callbacks_when_mark_failed_fails(mock_session):
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = True
    job.mark_failed.return_value = False
    cb = Mock()

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock(side_effect=RuntimeError("boom")))}),
        patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [cb]}),
    ):
        exec_job(job.id)

    cb.assert_not_called()


def test_run_final_callbacks_isolates_failures():
    job = _make_job_exec(job_key=JobKey.run_tests)
    failing = Mock(side_effect=RuntimeError("boom"), __name__="failing_cb")
    succeeding = Mock(__name__="succeeding_cb")

    with patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_tests: [failing, succeeding]}):
        run_final_callbacks(job)

    failing.assert_called_once_with(job)
    succeeding.assert_called_once_with(job)


def test_run_final_callbacks_noop_for_unknown_job_key():
    job = _make_job_exec(job_key="something-unregistered")

    with patch.dict(JOB_FINAL_CALLBACKS, {}, clear=False):
        run_final_callbacks(job)


def test_registered_callbacks_cover_notification_job_keys():
    assert JobKey.run_profile in JOB_FINAL_CALLBACKS
    assert JobKey.run_tests in JOB_FINAL_CALLBACKS
    assert JobKey.run_monitors in JOB_FINAL_CALLBACKS


def test_exec_job_marks_paused_without_settling_the_run(mock_session):
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = True
    resume_state = {"version": 1, "tasks": ["alpha\x1fa"], "completed": 1}
    handler = Mock(side_effect=JobParked("alpha", resume_state))

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=handler)}),
    ):
        exec_job(job.id)

    job.park.assert_called_once_with(resume_state)
    job.mark_completed.assert_not_called()
    job.mark_failed.assert_not_called()


def test_exec_job_fires_no_callbacks_on_pause(mock_session):
    """A paused run has not settled, so it must not notify or roll up scores."""
    job = _make_job_exec(job_key=JobKey.run_profile)
    job.mark_running.return_value = True
    handler = Mock(side_effect=JobParked("col_profiling", {"version": 1, "tasks": [], "completed": 0}))
    callback = Mock()

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_profile: JobConfig(handler=handler)}),
        patch.dict(JOB_FINAL_CALLBACKS, {JobKey.run_profile: [callback]}),
    ):
        exec_job(job.id)

    callback.assert_not_called()


def test_only_handlers_built_on_the_engine_are_pausable():
    """A handler that cannot see a pause request would hold shutdown open waiting for it."""
    for job_key in PAUSABLE_JOB_KEYS:
        module = sys.modules[JOB_DISPATCH[job_key].handler.__module__]
        built_on_engine = [
            obj
            for obj in vars(module).values()
            if isinstance(obj, type) and issubclass(obj, PausableJob) and obj is not PausableJob
        ]
        assert built_on_engine, f"{job_key} is pausable but {module.__name__} defines no PausableJob"


def test_exec_job_sweeps_stale_spill_directories(mock_session):
    """Orphaned spill is left by a killed job process, so a job process is where it is collected."""
    job = _make_job_exec(job_key=JobKey.run_tests)
    job.mark_running.return_value = True
    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {JobKey.run_tests: JobConfig(handler=Mock())}),
        patch("testgen.commands.exec_job.sweep_stale_spill_directories") as sweep,
    ):
        exec_job(job.id)

    sweep.assert_called_once_with()


_TERMINATED_JOB = textwrap.dedent("""
    import os, sys, time, uuid
    from pathlib import Path
    from unittest.mock import patch
    import testgen.__main__ as main
    from testgen.common.database.flavor import duckdb_flavor_service

    temp_directory = Path(sys.argv[1])

    def run(_):
        (temp_directory / f"{os.getpid()}-{uuid.uuid4().hex}").mkdir()
        (temp_directory / "ready").touch()
        time.sleep(60)

    with patch.object(duckdb_flavor_service, "TEMP_DIRECTORY", temp_directory), patch.object(main, "exec_job", run):
        main.exec_job_cmd.callback(uuid.uuid4())
""")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows terminates a job process without a signal")
def test_exec_job_removes_its_spill_when_terminated(tmp_path):
    """A canceled job is sent SIGTERM, which ends the process before its exit hooks delete the run's local file copies."""
    other_process = tmp_path / f"1-{uuid4().hex}"
    other_process.mkdir()
    proc = subprocess.Popen([sys.executable, "-c", _TERMINATED_JOB, str(tmp_path)])  # noqa: S603
    try:
        deadline = time.monotonic() + 60
        while not (tmp_path / "ready").exists():
            assert proc.poll() is None, "the job process exited before it was ready"
            assert time.monotonic() < deadline, "the job process never became ready"
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == -signal.SIGTERM
    finally:
        proc.kill()
        proc.wait()

    assert sorted(path.name for path in tmp_path.iterdir()) == sorted([other_process.name, "ready"])


def test_run_tests_handler_accepts_the_payload_the_submit_routes_build():
    """``exec_job`` dispatches with ``handler(**job_exec.kwargs)``, so a key the handler does not
    name raises TypeError inside a scheduler subprocess rather than at submit time. Bind the
    signature against the payload the REST route and the MCP tool produce."""
    signature = inspect.signature(run_test_execution)
    signature.bind(test_suite_id=str(uuid4()))
    signature.bind(test_suite_id=str(uuid4()), match_schema_name="reference_2026_09_10")
