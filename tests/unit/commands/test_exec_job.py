from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.commands.exec_job import exec_job
from testgen.commands.job_registry import JOB_DISPATCH, JOB_FINAL_CALLBACKS, run_final_callbacks
from testgen.common.models.job_execution import JobExecution

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    with patch("testgen.common.models.Session", return_value=session):
        yield session


def _make_job_exec(job_key="run-tests", status="claimed", **kwargs):
    job = MagicMock(spec=JobExecution)
    job.id = uuid4()
    job.job_key = job_key
    job.kwargs = {"test_suite_id": "suite-123"}
    job.source = "api"
    job.status = status
    job.configure_mock(**kwargs)
    return job


def test_exec_job_dispatches_run_tests(mock_session):
    job = _make_job_exec(job_key="run-tests")
    job.mark_running.return_value = True
    dispatch_mock = Mock(return_value="ok")

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-tests": dispatch_mock}),
    ):
        exec_job(job.id)

    job.mark_running.assert_called_once()
    dispatch_mock.assert_called_once_with(**job.kwargs)
    job.mark_completed.assert_called_once()


def test_exec_job_dispatches_run_profile(mock_session):
    job = _make_job_exec(job_key="run-profile")
    job.kwargs = {"table_group_id": "tg-123"}
    job.mark_running.return_value = True
    dispatch_mock = Mock(return_value="ok")

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-profile": dispatch_mock}),
    ):
        exec_job(job.id)

    dispatch_mock.assert_called_once_with(**job.kwargs)
    job.mark_completed.assert_called_once()


def test_exec_job_dispatches_run_monitors(mock_session):
    job = _make_job_exec(job_key="run-monitors")
    job.mark_running.return_value = True
    dispatch_mock = Mock(return_value="ok")

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-monitors": dispatch_mock}),
    ):
        exec_job(job.id)

    dispatch_mock.assert_called_once_with(**job.kwargs)


def test_exec_job_dispatches_run_test_generation(mock_session):
    job = _make_job_exec(job_key="run-test-generation")
    job.kwargs = {"test_suite_id": "suite-123", "generation_set": "Standard"}
    job.mark_running.return_value = True
    dispatch_mock = Mock(return_value="ok")

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-test-generation": dispatch_mock}),
    ):
        exec_job(job.id)

    dispatch_mock.assert_called_once_with(**job.kwargs)


def test_exec_job_marks_interrupted_on_unknown_key(mock_session):
    job = _make_job_exec(job_key="nonexistent")

    with patch.object(JobExecution, "get", return_value=job):
        exec_job(job.id)

    job.mark_interrupted.assert_called_once()
    assert "Unknown job key" in job.mark_interrupted.call_args[0][0]
    job.mark_running.assert_not_called()


def test_exec_job_skips_when_mark_running_fails(mock_session):
    job = _make_job_exec(job_key="run-tests")
    job.mark_running.return_value = False

    with patch.object(JobExecution, "get", return_value=job):
        exec_job(job.id)

    job.mark_completed.assert_not_called()


def test_exec_job_marks_interrupted_on_dispatch_error(mock_session):
    job = _make_job_exec(job_key="run-tests")
    job.mark_running.return_value = True

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-tests": Mock(side_effect=RuntimeError("boom"))}),
    ):
        exec_job(job.id)

    job.mark_interrupted.assert_called_once()
    assert "boom" in job.mark_interrupted.call_args[0][0]
    job.mark_completed.assert_not_called()


def test_exec_job_exits_on_missing_record(mock_session):
    with (
        patch.object(JobExecution, "get", return_value=None),
        pytest.raises(SystemExit, match="1"),
    ):
        exec_job(uuid4())


def test_job_dispatch_has_all_job_keys():
    assert "run-profile" in JOB_DISPATCH
    assert "run-tests" in JOB_DISPATCH
    assert "run-monitors" in JOB_DISPATCH
    assert "run-test-generation" in JOB_DISPATCH
    assert "run-score-update" in JOB_DISPATCH


def test_exec_job_fires_final_callbacks_on_success(mock_session):
    job = _make_job_exec(job_key="run-tests")
    job.mark_running.return_value = True
    job.mark_completed.return_value = True
    cb1, cb2 = Mock(), Mock()

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-tests": Mock(return_value="ok")}),
        patch.dict(JOB_FINAL_CALLBACKS, {"run-tests": [cb1, cb2]}),
    ):
        exec_job(job.id)

    cb1.assert_called_once_with(job)
    cb2.assert_called_once_with(job)


def test_exec_job_runs_callbacks_in_registered_order(mock_session):
    job = _make_job_exec(job_key="run-tests")
    job.mark_running.return_value = True
    job.mark_completed.return_value = True
    order = []
    cb1 = Mock(side_effect=lambda _: order.append("cb1"))
    cb2 = Mock(side_effect=lambda _: order.append("cb2"))

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-tests": Mock(return_value="ok")}),
        patch.dict(JOB_FINAL_CALLBACKS, {"run-tests": [cb1, cb2]}),
    ):
        exec_job(job.id)

    assert order == ["cb1", "cb2"]


def test_exec_job_skips_callbacks_when_mark_completed_fails(mock_session):
    job = _make_job_exec(job_key="run-tests")
    job.mark_running.return_value = True
    job.mark_completed.return_value = False
    cb = Mock()

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-tests": Mock(return_value="ok")}),
        patch.dict(JOB_FINAL_CALLBACKS, {"run-tests": [cb]}),
    ):
        exec_job(job.id)

    cb.assert_not_called()


def test_exec_job_fires_callbacks_on_interrupted(mock_session):
    job = _make_job_exec(job_key="run-tests")
    job.mark_running.return_value = True
    job.mark_interrupted.return_value = True
    cb = Mock()

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-tests": Mock(side_effect=RuntimeError("boom"))}),
        patch.dict(JOB_FINAL_CALLBACKS, {"run-tests": [cb]}),
    ):
        exec_job(job.id)

    cb.assert_called_once_with(job)


def test_exec_job_skips_callbacks_when_mark_interrupted_fails(mock_session):
    job = _make_job_exec(job_key="run-tests")
    job.mark_running.return_value = True
    job.mark_interrupted.return_value = False
    cb = Mock()

    with (
        patch.object(JobExecution, "get", return_value=job),
        patch.dict(JOB_DISPATCH, {"run-tests": Mock(side_effect=RuntimeError("boom"))}),
        patch.dict(JOB_FINAL_CALLBACKS, {"run-tests": [cb]}),
    ):
        exec_job(job.id)

    cb.assert_not_called()


def test_run_final_callbacks_isolates_failures():
    job = _make_job_exec(job_key="run-tests")
    failing = Mock(side_effect=RuntimeError("boom"), __name__="failing_cb")
    succeeding = Mock(__name__="succeeding_cb")

    with patch.dict(JOB_FINAL_CALLBACKS, {"run-tests": [failing, succeeding]}):
        run_final_callbacks(job)

    failing.assert_called_once_with(job)
    succeeding.assert_called_once_with(job)


def test_run_final_callbacks_noop_for_unknown_job_key():
    job = _make_job_exec(job_key="something-unregistered")

    with patch.dict(JOB_FINAL_CALLBACKS, {}, clear=False):
        run_final_callbacks(job)


def test_registered_callbacks_cover_notification_job_keys():
    assert "run-profile" in JOB_FINAL_CALLBACKS
    assert "run-tests" in JOB_FINAL_CALLBACKS
    assert "run-monitors" in JOB_FINAL_CALLBACKS
