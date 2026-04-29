from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.common.models.job_execution import JobExecution

pytestmark = pytest.mark.unit

MODULE = "testgen.common.models.job_execution"


def _returning_row(job, **overrides):
    """Create a mock RETURNING row from a job execution with overrides."""
    row = Mock()
    for col in JobExecution.__table__.columns:
        setattr(row, col.key, overrides.get(col.key, getattr(job, col.key, None)))
    return row


@pytest.fixture
def mock_session():
    session = MagicMock()
    with patch(f"{MODULE}.get_current_session", return_value=session):
        yield session


def test_submit_creates_pending_row(mock_session):
    result = JobExecution.submit(
        job_key="run-profile",
        kwargs={"table_group_id": "abc-123"},
        source="ui",
        project_code="DEFAULT",
    )

    mock_session.add.assert_called_once()
    mock_session.flush.assert_called_once()

    assert result.job_key == "run-profile"
    assert result.kwargs == {"table_group_id": "abc-123"}
    assert result.source == "ui"
    assert result.project_code == "DEFAULT"
    assert result.job_schedule_id is None


def test_submit_with_schedule_id(mock_session):
    schedule_id = uuid4()

    result = JobExecution.submit(
        job_key="run-tests",
        kwargs={"test_suite_id": "xyz"},
        source="scheduler",
        project_code="DEFAULT",
        job_schedule_id=schedule_id,
    )

    assert result.job_schedule_id == schedule_id
    assert result.source == "scheduler"


def test_submit_does_not_commit(mock_session):
    JobExecution.submit(
        job_key="run-profile",
        kwargs={},
        source="ui",
        project_code="DEFAULT",
    )

    mock_session.commit.assert_not_called()


def test_claim_actionable_claims_pending_rows(mock_session):
    row1 = JobExecution(id=uuid4(), status="pending", job_key="run-profile")
    row2 = JobExecution(id=uuid4(), status="pending", job_key="run-tests")
    mock_session.scalars.return_value.all.return_value = [row1, row2]

    result = JobExecution.claim_actionable(limit=5)

    assert len(result) == 2
    assert row1.status == "claimed"
    assert row2.status == "claimed"
    assert row1.claimed_at is not None
    assert row2.claimed_at is not None


def test_claim_actionable_passes_through_cancel_requested(mock_session):
    pending = JobExecution(id=uuid4(), status="pending", job_key="run-profile")
    cancel = JobExecution(id=uuid4(), status="cancel_requested", job_key="run-tests")
    mock_session.scalars.return_value.all.return_value = [pending, cancel]

    result = JobExecution.claim_actionable(limit=5)

    assert len(result) == 2
    assert pending.status == "claimed"
    assert cancel.status == "cancel_requested"


def test_claim_actionable_does_not_commit(mock_session):
    mock_session.scalars.return_value.all.return_value = [
        JobExecution(id=uuid4(), status="pending", job_key="run-profile")
    ]

    JobExecution.claim_actionable(limit=5)

    mock_session.commit.assert_not_called()


def test_claim_actionable_empty(mock_session):
    mock_session.scalars.return_value.all.return_value = []

    result = JobExecution.claim_actionable(limit=5)

    assert result == []


def test_get_by_id(mock_session):
    job_id = uuid4()
    expected = JobExecution(id=job_id, job_key="run-profile")
    mock_session.get.return_value = expected

    result = JobExecution.get(job_id)

    assert result is expected
    mock_session.get.assert_called_once_with(JobExecution, job_id)


def test_mark_running(mock_session):
    job = JobExecution(id=uuid4(), status="claimed")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="running")

    job.mark_running()

    assert job.status == "running"


def test_mark_completed(mock_session):
    job = JobExecution(id=uuid4(), status="running")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="completed")

    job.mark_completed()

    assert job.status == "completed"


def test_mark_interrupted_error(mock_session):
    job = JobExecution(id=uuid4(), status="running")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="error", error_message="Something went wrong")

    job.mark_interrupted("Something went wrong")

    assert job.status == "error"
    assert job.error_message == "Something went wrong"


def test_mark_interrupted_canceled(mock_session):
    job = JobExecution(id=uuid4(), status="cancel_requested")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="canceled")

    job.mark_interrupted("Process exited with code -15")

    assert job.status == "canceled"
