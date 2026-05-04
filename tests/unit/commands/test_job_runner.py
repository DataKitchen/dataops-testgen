from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.commands.job_runner import submit_and_wait
from testgen.common.models.job_execution import JobExecution, JobStatus

pytestmark = pytest.mark.unit

JOB_RUNNER_MODULE = "testgen.commands.job_runner"


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
        patch(f"{JOB_RUNNER_MODULE}.time.sleep"),
        pytest.raises(SystemExit, match="1"),
    ):
        submit_and_wait("run-tests", {"test_suite_id": "suite-123"}, "DEFAULT", no_wait=False)
