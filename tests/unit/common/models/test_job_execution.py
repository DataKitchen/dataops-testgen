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


def _mock_claim_results(mock_session, *jobs):
    """Feed the claim transition one RETURNING row per job, in claim order."""
    now = datetime.now(UTC)
    mock_session.execute.side_effect = [
        Mock(scalar_one_or_none=Mock(return_value=_returning_row(job, status="claimed", claimed_at=now)))
        for job in jobs
    ]


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
    _mock_claim_results(mock_session, row1, row2)

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
    _mock_claim_results(mock_session, pending)

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


def test_mark_running_coalesces_started_at_to_preserve_the_first_start(mock_session):
    """A resumed run re-enters RUNNING; started_at must not be restamped. The UPDATE coalesces
    the existing value so the run's original begin time -- its duration anchor -- is kept."""
    job = JobExecution(id=uuid4(), status="interrupted")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="running")

    job.mark_running()

    compiled = str(mock_session.execute.call_args[0][0].compile()).lower()
    assert "coalesce(job_executions.started_at" in compiled


def test_mark_completed(mock_session):
    job = JobExecution(id=uuid4(), status="running")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="completed")

    job.mark_completed()

    assert job.status == "completed"


def test_mark_failed_error(mock_session):
    job = JobExecution(id=uuid4(), status="running")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="error", error_message="Something went wrong")

    job.mark_failed("Something went wrong")

    assert job.status == "error"
    assert job.error_message == "Something went wrong"


def test_mark_failed_canceled(mock_session):
    job = JobExecution(id=uuid4(), status="cancel_requested")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="canceled")

    job.mark_failed("Process exited with code -15")

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


@pytest.mark.parametrize("status", ["interrupted", "resume_requested"])
def test_claim_actionable_claims_a_run_queued_to_continue(mock_session, status):
    """Both parked-and-queued statuses have to reach a worker through the ordinary poll.
    RESUME_REQUESTED is the release step of a requested pause, so if the poll skipped it, asking
    for a resume would look like it worked and the run would never move."""
    row = JobExecution(id=uuid4(), status=status, job_key="run-profile")
    mock_session.scalars.return_value.all.return_value = [row]
    _mock_claim_results(mock_session, row)

    result = JobExecution.claim_actionable(limit=5)

    assert len(result) == 1
    assert row.status == "claimed"


def test_the_poll_query_cannot_reach_a_paused_row(mock_session):
    """A paused run is held, not queued: the poll must not select it, or a requested pause would
    auto-continue and the whole distinction from an interrupt would collapse.

    Reads the status list off the query the poll actually issues, since a mocked session applies
    no filter of its own and would hand back whatever it was given."""
    mock_session.scalars.return_value.all.return_value = []

    JobExecution.claim_actionable(limit=5)

    selected = next(
        v for v in mock_session.scalars.call_args[0][0].compile().params.values()
        if isinstance(v, list | tuple)
    )
    assert JobStatus.PAUSED not in set(selected)
    assert JobStatus.RESUME_REQUESTED in set(selected)


def test_claim_actionable_drops_a_row_it_lost_the_race_for(mock_session):
    row = JobExecution(id=uuid4(), status="pending", job_key="run-profile")
    mock_session.scalars.return_value.all.return_value = [row]
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    assert JobExecution.claim_actionable(limit=5) == []


def test_actionable_statuses_match_the_transition_graph():
    """Anything claim_actionable transitions must be allowed to reach CLAIMED."""
    claimable = set(JobStatus.claimable())
    assert set(JobExecution.ACTIONABLE_STATUSES) - claimable == {JobStatus.CANCEL_REQUESTED}


@pytest.mark.parametrize(
    ("status", "target", "allowed"),
    [
        (JobStatus.RUNNING, JobStatus.INTERRUPT_REQUESTED, True),
        (JobStatus.CLAIMED, JobStatus.INTERRUPT_REQUESTED, False),
        (JobStatus.INTERRUPT_REQUESTED, JobStatus.INTERRUPTED, True),
        (JobStatus.INTERRUPT_REQUESTED, JobStatus.COMPLETED, True),
        (JobStatus.INTERRUPT_REQUESTED, JobStatus.ERROR, True),
        (JobStatus.INTERRUPT_REQUESTED, JobStatus.INTERRUPT_REQUESTED, True),
        (JobStatus.INTERRUPTED, JobStatus.CLAIMED, True),
        (JobStatus.INTERRUPTED, JobStatus.CANCEL_REQUESTED, True),
        (JobStatus.INTERRUPTED, JobStatus.ERROR, False),
        (JobStatus.COMPLETED, JobStatus.INTERRUPT_REQUESTED, False),
        (JobStatus.RUNNING, JobStatus.PAUSE_REQUESTED, True),
        (JobStatus.CLAIMED, JobStatus.PAUSE_REQUESTED, False),
        (JobStatus.PAUSE_REQUESTED, JobStatus.PAUSED, True),
        (JobStatus.PAUSE_REQUESTED, JobStatus.COMPLETED, True),
        (JobStatus.PAUSE_REQUESTED, JobStatus.ERROR, True),
        (JobStatus.PAUSE_REQUESTED, JobStatus.PAUSE_REQUESTED, True),
        (JobStatus.PAUSED, JobStatus.RESUME_REQUESTED, True),
        (JobStatus.PAUSED, JobStatus.CANCEL_REQUESTED, True),
        # The line between the two intents: no poll may take a paused run.
        (JobStatus.PAUSED, JobStatus.CLAIMED, False),
        (JobStatus.RESUME_REQUESTED, JobStatus.CLAIMED, True),
        (JobStatus.RESUME_REQUESTED, JobStatus.CANCEL_REQUESTED, True),
        (JobStatus.INTERRUPT_REQUESTED, JobStatus.PAUSED, False),
        (JobStatus.PAUSE_REQUESTED, JobStatus.INTERRUPTED, False),
    ],
)
def test_stop_transition_edges(status, target, allowed):
    assert (status in JobStatus.sources_for(target)) is allowed


@pytest.mark.parametrize(
    ("status", "parked"),
    [("interrupt_requested", "interrupted"), ("pause_requested", "paused")],
)
def test_park_persists_the_checkpoint_where_the_request_points(mock_session, status, parked):
    job = JobExecution(id=uuid4(), status=status, job_key="run-profile")
    state = {"version": 1, "tasks": ["alpha\x1fa"], "completed": 1}
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(
        job, status=parked, resume_state=state
    )

    assert job.park(state) is True
    assert job.status == parked
    assert job.resume_state == state


def test_park_offers_both_targets_so_the_row_decides(mock_session):
    """The job never learns which intent stopped it -- it names both and the CASE picks by the
    status already in the database, which is what keeps the choice atomic with the write."""
    job = JobExecution(id=uuid4(), status="pause_requested", job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="paused")

    job.park({"version": 1, "tasks": [], "completed": 0})

    # The status pick specifically: the billing write emits a CASE into the same clause, so a
    # bare "CASE" would pass even if the target choice stopped being one.
    set_clause = str(mock_session.execute.call_args[0][0]).split(" WHERE ")[0]
    assert "status=CASE" in set_clause


def test_request_pause_is_refused_for_a_job_that_cannot_honor_it(mock_session):
    """Nothing would ever park the row, so it would read as pausing with no process behind it."""
    job = JobExecution(id=uuid4(), status="running", job_key="run-score-update")

    assert job.request_pause() is False
    mock_session.execute.assert_not_called()


def test_request_pause_asks_a_running_pausable_job(mock_session):
    job = JobExecution(id=uuid4(), status="running", job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(
        job, status="pause_requested"
    )

    assert job.request_pause() is True
    assert job.status == "pause_requested"


def test_request_resume_hands_a_paused_run_back_to_the_poll(mock_session):
    job = JobExecution(id=uuid4(), status="paused", job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(
        job, status="resume_requested"
    )

    assert job.request_resume() is True
    assert job.status == "resume_requested"


def test_recover_stale_cancels_every_status_that_implies_a_dead_process(mock_session):
    mock_session.scalars.return_value.all.return_value = [uuid4(), uuid4()]

    # Three passes now -- hold the paused, continue the rest of the checkpointed, cancel what
    # is left -- so all three are counted.
    assert JobExecution.recover_stale() == 6

    assert _narrows_to(_settling_pass(mock_session, JobStatus.CANCEL_REQUESTED), JobStatus.stale_recoverable())


def _billing_expression(statement):
    """The rendered ``active_seconds`` assignment, with its bind values inlined.

    Read out of the SET clause rather than by picking a parameter: the guard in WHERE binds
    status lists too, and matching on content alone would happily return the wrong one.
    """
    rendered = str(statement.compile(compile_kwargs={"literal_binds": True})).split(" WHERE ")[0]
    return rendered[rendered.index("active_seconds=CASE"):]


def _narrows_to(compiled, statuses):
    """Whether the statement's guard admits exactly ``statuses``.

    Matched by content, not by parameter name: the names shift as a statement gains clauses, so
    pinning one breaks on a change that merely adds a bind rather than on a change of behaviour.
    """
    wanted = set(statuses)
    return any(isinstance(v, list | tuple) and set(v) == wanted for v in compiled.params.values())


def _settling_pass(mock_session, target):
    """The recover_stale statement that settles rows into ``target``.

    Selected by target rather than call order: recover_stale runs several passes and which one
    goes first is an implementation detail these tests should not pin.
    """
    for call in mock_session.scalars.call_args_list:
        compiled = call[0][0].compile()
        if compiled.params["status"] == target:
            return compiled
    raise AssertionError(f"no pass settled anything into {target}")


def test_recover_stale_holds_a_checkpointed_pause_rather_than_queueing_it(mock_session):
    """A pause is the one stop a restart must not undo. Continuing it would land INTERRUPTED,
    which the next poll claims -- silently resuming a run somebody chose to stop.

    Runs before the cancel pass, so the pause is settled by the time that pass looks."""
    mock_session.scalars.return_value.all.return_value = []

    JobExecution.recover_stale()

    park = _settling_pass(mock_session, JobStatus.PAUSED)
    assert JobStatus.PAUSE_REQUESTED in park.params.values()
    # Same evidence the continue pass demands: without a checkpoint there is no progress to hold.
    assert "resume_state IS NOT NULL" in str(park)


def test_recover_stale_cancels_a_pause_that_never_checkpointed(mock_session):
    """The cancel pass takes the whole stale set, so a pause that never got far enough to write
    a checkpoint falls through to it rather than parking as progress it does not have."""
    mock_session.scalars.return_value.all.return_value = []

    JobExecution.recover_stale()

    cancel = _settling_pass(mock_session, JobStatus.CANCEL_REQUESTED)
    assert _narrows_to(cancel, JobStatus.stale_recoverable())
    assert "resume_state IS NOT NULL" not in str(cancel)


def test_recover_stale_continues_a_row_that_carries_a_checkpoint(mock_session):
    """The checkpoint is the job's last write before it unwinds, so a row holding one has its
    work accounted for and only its exit went unrecorded. Canceling it would throw that away."""
    mock_session.scalars.return_value.all.return_value = []

    JobExecution.recover_stale()

    resume = _settling_pass(mock_session, JobStatus.INTERRUPTED)
    assert "resume_state IS NOT NULL" in str(resume)


def test_recover_stale_never_continues_a_row_with_no_checkpoint(mock_session):
    """Without a checkpoint the status alone is not evidence the process finished -- exec-job
    outlives its scheduler -- so continuing would hand a second worker a run still writing."""
    mock_session.scalars.return_value.all.return_value = []

    JobExecution.recover_stale()

    for call in mock_session.scalars.call_args_list:
        compiled = call[0][0].compile()
        if compiled.params["status"] == JobStatus.INTERRUPTED:
            assert "resume_state IS NOT NULL" in str(compiled)


def test_request_interrupt_bulk_is_empty_without_pausable_keys(mock_session):
    assert JobExecution.request_interrupt_bulk([uuid4()], []) == set()
    mock_session.scalars.assert_not_called()


def test_transition_bulk_is_empty_without_ids(mock_session):
    assert JobExecution.request_interrupt_bulk([], ["run-profile"]) == set()
    mock_session.scalars.assert_not_called()


def test_request_interrupt_bulk_only_reports_the_jobs_it_asked(mock_session):
    """The transition guard accepts a job already stopping, so asking twice is harmless -- but
    the query narrows to RUNNING, so the returned ids are the ones this call actually asked.
    """
    JobExecution.request_interrupt_bulk([uuid4()], ["run-profile"])

    params = mock_session.scalars.call_args[0][0].compile().params
    assert JobStatus.RUNNING in params.values()


def test_park_accumulates_the_segment_only_from_a_status_that_was_working(mock_session):
    """Parking is idempotent by way of the self-loops, and exec_job re-parks as a belt. Without
    the CASE the belt would add the same working segment a second time.

    The guard is derived from the lifecycle, not chosen: the only working statuses that reach a
    parked one are the two requests, so it narrows to exactly those."""
    job = JobExecution(id=uuid4(), status="pause_requested", job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="paused")

    job.park({"version": 1, "tasks": [], "completed": 0})

    statement = mock_session.execute.call_args[0][0]
    # Only the SET clause: RETURNING lists every column, active_seconds included.
    set_clause = str(statement).split(" WHERE ")[0]
    assert "active_seconds=CASE" in set_clause
    # Added to whatever earlier processes recorded, not written over it, or the sum across
    # resumes would collapse to the last segment.
    assert "coalesce(job_executions.active_seconds" in set_clause
    # Measured from the claim, which every claim restamps. From started_at instead, each resume
    # would re-count every segment before it.
    assert "job_executions.claimed_at" in set_clause
    # Spelled out rather than derived the way the code derives it, so narrowing either the
    # working set or the transition map fails here rather than passing silently.
    assert _narrows_to(statement.compile(), {JobStatus.INTERRUPT_REQUESTED, JobStatus.PAUSE_REQUESTED})


@pytest.mark.parametrize("transition", ["mark_completed", "mark_failed"])
def test_a_terminal_transition_records_what_the_run_worked(mock_session, transition):
    job = JobExecution(id=uuid4(), status="running", job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="completed")

    getattr(job, transition)(*(["boom"] if transition == "mark_failed" else []))

    set_clause = str(mock_session.execute.call_args[0][0]).split(" WHERE ")[0]
    assert "active_seconds=" in set_clause
    assert "coalesce(job_executions.active_seconds" in set_clause
    assert "job_executions.claimed_at" in set_clause


def test_request_cancel_bills_the_segment_the_run_worked(mock_session):
    """Billed here and not at mark_canceled, which cannot tell a run that was working from one
    that was parked or never started -- by then every row on its way out reads CANCEL_REQUESTED."""
    job = JobExecution(id=uuid4(), status="running", job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(
        job, status="cancel_requested"
    )

    job.request_cancel()

    set_clause = str(mock_session.execute.call_args[0][0]).split(" WHERE ")[0]
    assert "active_seconds=CASE" in set_clause
    assert "job_executions.claimed_at" in set_clause


def test_mark_canceled_bills_nothing(mock_session):
    """The segment was billed when the cancel was asked for. Billing again here would re-charge
    a run that was parked when the cancel arrived, since by now every row on its way out reads
    the same status and the parked one can no longer be told apart.

    The cost is that the window between the request and the process actually stopping goes
    unbilled -- a terminate plus its grace period -- which is a bounded undercount rather than
    time nobody worked."""
    job = JobExecution(id=uuid4(), status="cancel_requested", job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="canceled")

    job.mark_canceled()

    assert "active_seconds=" not in str(mock_session.execute.call_args[0][0]).split(" WHERE ")[0]


@pytest.mark.parametrize("parked", ["paused", "interrupted"])
def test_a_parked_run_is_not_billed_for_standing_still(mock_session, parked):
    """A parked run has stopped, and the pause is exactly where that span runs to hours. Asks
    for a cancel from the parked status, since that is the transition a user reaches for."""
    job = JobExecution(id=uuid4(), status=parked, job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(
        job, status="cancel_requested"
    )

    job.request_cancel()

    # The clause is present -- other sources of this transition do bill -- so what matters is
    # that the parked status is not among the ones it admits.
    billing = _billing_expression(mock_session.execute.call_args[0][0])
    assert f"'{parked}'" not in billing
    assert "'running'" in billing


def test_a_run_that_never_started_is_not_billed(mock_session):
    """A row can be claimed and never dispatched. The span from its claim is nobody's work, so
    settling it records nothing rather than charging it for the wait."""
    job = JobExecution(id=uuid4(), status="running", job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="completed")

    job.mark_completed()

    # Guarded on the run having started, not on its status alone.
    assert "started_at IS NOT NULL" in str(mock_session.execute.call_args[0][0])


def test_a_terminal_transition_does_not_rebill_a_cancel(mock_session):
    """mark_failed pairs a billable target with a non-billable one: ERROR arrives from a working
    status, CANCELED from a cancel that was already billed when it was asked for. Billing from
    every source of the pair would charge a cancel-then-crash row twice."""
    job = JobExecution(id=uuid4(), status="running", job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = _returning_row(job, status="error")

    job.mark_failed("boom")

    billing = _billing_expression(mock_session.execute.call_args[0][0])
    assert "'cancel_requested'" not in billing
    assert "'running'" in billing


def test_the_recovery_passes_bill_what_the_dead_process_worked(mock_session):
    """The only route that bills a row the current process never worked. Without it a settled
    run carries nothing and every display reads it as no work at all."""
    mock_session.scalars.return_value.all.return_value = []

    JobExecution.recover_stale()

    for target in (JobStatus.PAUSED, JobStatus.INTERRUPTED, JobStatus.CANCEL_REQUESTED):
        statement = str(_settling_pass(mock_session, target)).split(" WHERE ")[0]
        assert "active_seconds=CASE" in statement, target
        assert "started_at IS NOT NULL" in statement, target


@pytest.mark.parametrize(
    ("method", "status"), [("claim", "pending"), ("mark_running", "claimed"), ("request_pause", "running")]
)
def test_a_transition_into_a_working_status_bills_nothing(mock_session, method, status):
    """The segment runs from the claim, not from the previous transition, so a step taken while
    the run is still working would add the whole span again. CLAIMED to RUNNING is such a step,
    and billing it would charge every run twice for its process launch."""
    job = JobExecution(id=uuid4(), status=status, job_key="run-profile")
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    getattr(job, method)()

    assert "active_seconds=" not in str(mock_session.execute.call_args[0][0]).split(" WHERE ")[0]


def test_asking_to_interrupt_bills_nothing(mock_session):
    """The run keeps working while it drains toward a boundary, so the request does not end its
    working period -- parking does."""
    mock_session.scalars.return_value.all.return_value = []

    JobExecution.request_interrupt_bulk([uuid4()], ["run-profile"])

    assert "active_seconds=" not in str(mock_session.scalars.call_args[0][0]).split(" WHERE ")[0]
