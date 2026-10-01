from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.commands.job_runner import submit_and_wait
from testgen.common.enums import JobStatus
from testgen.common.models.job_execution import QUEUED_MESSAGE, JobExecution

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


def test_submit_and_wait_keeps_waiting_through_interrupted(mock_session):
    """An interrupted run is not terminal and continues unattended, so the wait keeps polling
    and the scheduler restart that picks it up is what ends the wait."""
    submitted = _make_job_exec(status=JobStatus.CLAIMED)
    interrupted = _make_job_exec(status=JobStatus.INTERRUPTED)
    completed = _make_job_exec(status=JobStatus.COMPLETED)
    mock_session.flush = Mock()

    with (
        patch.object(JobExecution, "submit", return_value=submitted),
        patch.object(JobExecution, "get", side_effect=[interrupted, completed]) as get_mock,
        patch(f"{JOB_RUNNER_MODULE}.time.sleep"),
    ):
        submit_and_wait("run-tests", {"test_suite_id": "suite-123"}, "DEFAULT", no_wait=False)

    assert get_mock.call_count == 2  # polled past INTERRUPTED, broke only on the terminal status


def test_submit_and_wait_gives_up_on_a_paused_run(mock_session):
    """A pause is where the wait has to stop. Nothing moves the run until a resume is asked
    for, so polling on would block for as long as the run stays parked."""
    submitted = _make_job_exec(status=JobStatus.CLAIMED)
    paused = _make_job_exec(status=JobStatus.PAUSED)
    mock_session.flush = Mock()

    with (
        patch.object(JobExecution, "submit", return_value=submitted),
        # A bounded side_effect, not return_value: if the break ever regresses, the mock runs
        # dry and the test fails instead of spinning on a status that never settles.
        patch.object(JobExecution, "get", side_effect=[paused, paused]) as get_mock,
        patch(f"{JOB_RUNNER_MODULE}.time.sleep"),
        pytest.raises(SystemExit) as exited,
    ):
        submit_and_wait("run-tests", {"test_suite_id": "suite-123"}, "DEFAULT", no_wait=False)

    assert exited.value.code == 1  # an unfinished run is not a successful command
    assert get_mock.call_count == 1  # broke on the first poll rather than waiting it out


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


def test_submit_and_wait_says_once_that_a_run_is_queued(mock_session, capsys):
    submitted = _make_job_exec(status=JobStatus.PENDING)
    queued = _make_job_exec(status=JobStatus.QUEUED)
    completed = _make_job_exec(status=JobStatus.COMPLETED)
    mock_session.flush = Mock()

    with (
        patch.object(JobExecution, "submit", return_value=submitted),
        patch.object(JobExecution, "get", side_effect=[queued, queued, completed]),
        patch(f"{JOB_RUNNER_MODULE}.time.sleep"),
        patch(f"{JOB_RUNNER_MODULE}._print_run_summary"),
    ):
        submit_and_wait("run-tests", {"test_suite_id": "suite-123"}, "DEFAULT", no_wait=False)

    assert capsys.readouterr().out.count(QUEUED_MESSAGE) == 1
