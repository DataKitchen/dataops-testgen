from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.commands.exec_job import JOB_DISPATCH, exec_job, submit_and_wait
from testgen.common.models.job_execution import JobExecution, JobStatus

pytestmark = pytest.mark.unit

EXEC_JOB_MODULE = "testgen.commands.exec_job"


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


def test_submit_and_wait_creates_job(mock_session):
    job = _make_job_exec()
    job.status = JobStatus.COMPLETED
    mock_session.flush = Mock()

    with (
        patch.object(JobExecution, "submit", return_value=job) as submit_mock,
        patch.object(JobExecution, "get", return_value=job),
    ):
        submit_and_wait("run-tests", {"test_suite_id": "suite-123"}, "DEFAULT", no_wait=False)

    submit_mock.assert_called_once_with(
        job_key="run-tests",
        kwargs={"test_suite_id": "suite-123"},
        source="cli",
        project_code="DEFAULT",
    )


def test_submit_and_wait_no_wait_returns_immediately(mock_session):
    job = _make_job_exec()
    mock_session.flush = Mock()

    with (
        patch.object(JobExecution, "submit", return_value=job) as submit_mock,
    ):
        submit_and_wait("run-tests", {"test_suite_id": "suite-123"}, "DEFAULT", no_wait=True)

    submit_mock.assert_called_once()


def test_submit_and_wait_exits_on_error(mock_session):
    job = _make_job_exec()
    job.status = JobStatus.ERROR
    job.error_message = "something broke"
    mock_session.flush = Mock()

    with (
        patch.object(JobExecution, "submit", return_value=job),
        patch.object(JobExecution, "get", return_value=job),
        patch(f"{EXEC_JOB_MODULE}.time.sleep"),
        pytest.raises(SystemExit, match="1"),
    ):
        submit_and_wait("run-tests", {"test_suite_id": "suite-123"}, "DEFAULT", no_wait=False)


def test_job_dispatch_has_all_job_keys():
    assert "run-profile" in JOB_DISPATCH
    assert "run-tests" in JOB_DISPATCH
    assert "run-monitors" in JOB_DISPATCH
    assert "run-test-generation" in JOB_DISPATCH
