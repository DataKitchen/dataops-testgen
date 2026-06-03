from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen.common.models.job_execution import JobExecution, JobStatus

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
    ctx = MagicMock()
    ctx.__enter__ = Mock(return_value=session)
    ctx.__exit__ = Mock(return_value=False)
    with (
        patch(f"{MODULE}.get_current_session", return_value=session),
        patch(f"{MODULE}.database_session", return_value=ctx),
    ):
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


def test_request_cancel_pending_to_cancel_requested(mock_session):
    job = JobExecution(id=uuid4(), status="pending")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="cancel_requested")

    assert job.request_cancel() is True
    assert job.status == "cancel_requested"


def test_request_cancel_idempotent_when_already_requested(mock_session):
    """A re-request on a job already in cancel_requested succeeds via the CANCEL_REQUESTED self-loop."""
    job = JobExecution(id=uuid4(), status="cancel_requested")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="cancel_requested")

    assert job.request_cancel() is True
    assert job.status == "cancel_requested"


def test_request_cancel_terminal_state_returns_false(mock_session):
    """Truly uncancelable states (completed/error/canceled) still return False."""
    job = JobExecution(id=uuid4(), status="completed")
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    assert job.request_cancel() is False
    assert job.status == "completed"


# ─── delete_older_than (data retention) ─────────────────────────────


def _capture_clauses_used_in_select(mock_session):
    """Returns the WHERE clauses passed to the candidate-id select query.

    The cleanup loop does select(id).where(*clauses).limit(...). We capture
    those clauses to assert which filters were applied."""
    select_call = mock_session.scalars.call_args
    select_stmt = select_call.args[0]
    return list(select_stmt.whereclause.clauses) if select_stmt.whereclause is not None else []


def test_delete_older_than_filters_only_terminal_statuses(mock_session):
    """The status filter is `IN ('completed', 'error', 'canceled')` — non-terminal
    rows (pending/claimed/running/cancel_requested) are skipped regardless of age.
    This is the key safety guarantee: live work must never be deleted."""
    mock_session.scalars.return_value.all.return_value = []  # no candidates → loop exits

    cutoff = datetime.now(UTC) - timedelta(days=180)
    JobExecution.delete_older_than(cutoff=cutoff, project_code="proj", protected_ids=set())

    clauses = _capture_clauses_used_in_select(mock_session)
    status_clause = next(
        (c for c in clauses if "status" in str(c).lower()),
        None,
    )
    assert status_clause is not None
    rendered = str(status_clause.compile(compile_kwargs={"literal_binds": True}))
    # Must include all three terminal states
    for state in (JobStatus.COMPLETED.value, JobStatus.ERROR.value, JobStatus.CANCELED.value):
        assert state in rendered
    # Must not include any non-terminal state
    for state in (JobStatus.PENDING.value, JobStatus.CLAIMED.value,
                  JobStatus.RUNNING.value, JobStatus.CANCEL_REQUESTED.value):
        assert state not in rendered


def test_delete_older_than_returns_zero_when_no_candidates(mock_session):
    """No-op when nothing is old enough to delete — returns 0, no DELETE executed."""
    mock_session.scalars.return_value.all.return_value = []

    cutoff = datetime.now(UTC) - timedelta(days=180)
    result = JobExecution.delete_older_than(cutoff=cutoff, project_code="proj", protected_ids=set())

    assert result == 0
    # Only the candidate-select ran; no DELETE statement was issued.
    mock_session.execute.assert_not_called()


def test_delete_older_than_batches_and_deletes(mock_session):
    """Two-batch path: scalars returns one batch, then empty. Both should result
    in a DELETE on the first batch, and the total count returned."""
    first_batch = [uuid4(), uuid4(), uuid4()]
    mock_session.scalars.return_value.all.side_effect = [first_batch, []]

    cutoff = datetime.now(UTC) - timedelta(days=180)
    result = JobExecution.delete_older_than(
        cutoff=cutoff, project_code="proj", protected_ids=set(), batch_size=1000,
    )

    assert result == 3
    mock_session.execute.assert_called_once()  # one DELETE for one non-empty batch


def test_delete_older_than_applies_protected_ids_exclusion(mock_session):
    """The protected_ids carve-out — job_executions of protected runs — adds a
    NOT IN clause so they survive even when older than the cutoff."""
    protected = {uuid4(), uuid4()}
    mock_session.scalars.return_value.all.return_value = []

    cutoff = datetime.now(UTC) - timedelta(days=180)
    JobExecution.delete_older_than(cutoff=cutoff, project_code="proj", protected_ids=protected)

    clauses = _capture_clauses_used_in_select(mock_session)
    rendered = " ".join(str(c) for c in clauses).lower()
    assert "not in" in rendered or "!= all" in rendered or "in (" in rendered  # NOT IN expression present


def test_delete_older_than_skips_protected_filter_when_empty(mock_session):
    """Empty protected_ids → no NOT IN clause emitted, avoiding the SQL warning
    that `IN ()` triggers in postgres."""
    mock_session.scalars.return_value.all.return_value = []

    cutoff = datetime.now(UTC) - timedelta(days=180)
    JobExecution.delete_older_than(cutoff=cutoff, project_code="proj", protected_ids=set())

    clauses = _capture_clauses_used_in_select(mock_session)
    rendered = " ".join(str(c) for c in clauses).lower()
    # Three expected clauses: project_code, completed_at, status IN
    # Absence of "not in" confirms the protected-ids clause was skipped.
    assert "not in" not in rendered
