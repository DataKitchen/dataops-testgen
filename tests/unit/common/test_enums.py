import pytest

from testgen.common.enums import (
    JOB_STATUS_LABEL,
    STOPPABLE_ONLY_STATUSES,
    WORKING_STATUSES,
    JobStatus,
    SuiteType,
    run_duration_seconds,
)
from testgen.common.models.profiling_run import ProfilingRunSummary
from testgen.common.models.test_run import TestRunSummary

pytestmark = pytest.mark.unit


def test_job_status_label_covers_every_status():
    # A missing entry would surface a raw lowercase status code (e.g. "cancel_requested")
    # in run lists, emails, and MCP output instead of a display label.
    assert set(JOB_STATUS_LABEL) == set(JobStatus)


def test_terminal_and_active_partition_every_status():
    assert set(JobStatus.terminal()) | set(JobStatus.active()) == set(JobStatus)
    assert not set(JobStatus.terminal()) & set(JobStatus.active())


def test_terminal_is_read_off_the_transition_graph():
    # A status is terminal exactly when the graph gives it nowhere to go, so classifying a
    # new status is a matter of declaring its transitions and nothing else.
    assert set(JobStatus.terminal()) == {JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCELED}
    for status in JobStatus.terminal():
        assert JobStatus.sources_for(status), f"{status} should still be reachable"


def test_claimable_is_read_off_the_transition_graph():
    assert set(JobStatus.claimable()) == {
        JobStatus.PENDING, JobStatus.INTERRUPTED, JobStatus.RESUME_REQUESTED, JobStatus.QUEUED,
    }
    assert JobStatus.claimable() == JobStatus.sources_for(JobStatus.CLAIMED)


def test_queued_is_reached_only_from_a_status_waiting_for_a_claim():
    """The poll queues what it could not claim, so QUEUED is entered only from the statuses a claim
    would have taken, and it stays claimable so a freed slot picks it up."""
    assert set(JobStatus.sources_for(JobStatus.QUEUED)) == set(JobStatus.claimable()) - {JobStatus.QUEUED}
    assert JobStatus.QUEUED in JobStatus.active()
    assert JobStatus.QUEUED not in JobStatus.stale_recoverable()
    assert JobStatus.QUEUED not in JobStatus.sources_for(JobStatus.PAUSE_REQUESTED)


def test_interrupted_is_queued_work():
    # The property the lifecycle rests on: a stopped run is claimable, so the next poll continues
    # it. Everything else about the shutdown path follows from this.
    assert JobStatus.INTERRUPTED in JobStatus.claimable()
    assert JobStatus.INTERRUPTED in JobStatus.active()
    assert JobStatus.INTERRUPTED not in JobStatus.stale_recoverable()


def test_pending_is_never_swept_at_startup():
    # A pending job was never claimed, so no process died; the first poll starts it. Sweeping it
    # would cancel queued follow-up jobs (e.g. generation) that simply had not run yet.
    assert JobStatus.PENDING in JobStatus.active()
    assert JobStatus.PENDING not in JobStatus.stale_recoverable()


def test_stale_recoverable_is_what_a_dead_process_leaves_behind():
    # Each of these implies a process that is now gone, so a restart settles it. Everything
    # else in active() is either queued for a poll or parked waiting to be resumed.
    assert set(JobStatus.stale_recoverable()) == {
        JobStatus.CLAIMED, JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED,
        JobStatus.INTERRUPT_REQUESTED, JobStatus.PAUSE_REQUESTED,
    }


@pytest.mark.parametrize(
    "statuses",
    [JobStatus.terminal(), JobStatus.active(), JobStatus.claimable(), JobStatus.stale_recoverable()],
)
def test_classifications_are_tuples_in_declaration_order(statuses):
    # These feed SQL IN lists, so an unordered set would render the same query differently
    # between processes.
    assert isinstance(statuses, tuple)
    assert list(statuses) == [status for status in JobStatus if status in set(statuses)]


def test_run_summaries_share_the_job_status_label_map():
    assert TestRunSummary.STATUS_LABEL is JOB_STATUS_LABEL
    assert ProfilingRunSummary.STATUS_LABEL is JOB_STATUS_LABEL


def test_stoppable_statuses_are_entered_only_from_running_or_each_other():
    """Nothing derives the constant, so the graph is what keeps it honest."""
    for status in STOPPABLE_ONLY_STATUSES:
        sources = set(JobStatus.sources_for(status))
        assert sources <= STOPPABLE_ONLY_STATUSES | {JobStatus.RUNNING}, status


def test_no_stoppable_status_is_left_out_of_the_constant():
    """A status entered only from a stopped one belongs in STOPPABLE_ONLY_STATUSES too."""
    for status in set(JobStatus) - STOPPABLE_ONLY_STATUSES:
        sources = set(JobStatus.sources_for(status))
        assert not sources or not sources <= STOPPABLE_ONLY_STATUSES, status


def test_stoppable_statuses_are_not_part_of_the_ordinary_lifecycle():
    assert not STOPPABLE_ONLY_STATUSES & {
        JobStatus.PENDING, JobStatus.CLAIMED, JobStatus.RUNNING,
        JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCEL_REQUESTED, JobStatus.CANCELED,
    }


def test_a_paused_run_is_held_rather_than_queued():
    # The property that separates the two stop intents: no poll may pick a paused run up, or a
    # requested pause would auto-continue like an interrupt and the distinction would be cosmetic.
    assert JobStatus.PAUSED not in JobStatus.claimable()
    assert JobStatus.PAUSED in JobStatus.active()
    assert JobStatus.PAUSED not in JobStatus.stale_recoverable()


def test_resume_is_what_puts_a_paused_run_back_in_the_queue():
    assert JobStatus.RESUME_REQUESTED in JobStatus.sources_for(JobStatus.CLAIMED)
    assert JobStatus.PAUSED in JobStatus.sources_for(JobStatus.RESUME_REQUESTED)
    assert JobStatus.RESUME_REQUESTED not in JobStatus.stale_recoverable()


def test_the_two_park_targets_are_reached_from_disjoint_statuses():
    """What lets ``JobExecution.park`` name both targets and let the row's own status decide.
    Overlapping sources would make its CASE order-dependent and the choice arbitrary."""
    assert not set(JobStatus.sources_for(JobStatus.INTERRUPTED)) & set(JobStatus.sources_for(JobStatus.PAUSED))


def test_a_parked_row_can_be_parked_again():
    """The engine settles the row itself, and exec_job re-parks it as a belt for a stop that
    unwound without settling. Without the self-loops that belt logs a failed transition."""
    assert JobStatus.INTERRUPTED in JobStatus.sources_for(JobStatus.INTERRUPTED)
    assert JobStatus.PAUSED in JobStatus.sources_for(JobStatus.PAUSED)


def test_every_stopped_run_can_still_be_canceled():
    # A run parked with no process behind it is exactly the one a user is most likely to give
    # up on, and cancel is the only way out that does not need a worker.
    for status in STOPPABLE_ONLY_STATUSES:
        assert status in JobStatus.sources_for(JobStatus.CANCEL_REQUESTED), status


def test_a_run_with_more_work_coming_reports_no_duration_yet():
    """Only the segments it already finished are recorded. A queued run counts too: the next
    poll takes it without anybody asking, so its total grows the way a working run's does."""
    for status in WORKING_STATUSES | frozenset(JobStatus.claimable()):
        assert run_duration_seconds(120.0, status) is None, status


def test_a_settled_or_paused_run_reports_the_time_it_worked():
    """A requested pause is the one stop that holds, so its total is final until somebody
    releases it."""
    # Plain strings too, which is what every caller reads off the status column.
    for status in (JobStatus.COMPLETED, JobStatus.CANCELED, JobStatus.PAUSED, "paused"):
        assert run_duration_seconds(120.0, status) == 120.0, status


def test_every_status_either_reports_a_duration_or_withholds_one():
    """Spelled out rather than derived the way the code derives it, so a status crossing between
    the two fails here rather than quietly changing what every duration display shows."""
    reporting = {status for status in JobStatus if run_duration_seconds(1.0, status) is not None}

    assert reporting == {
        JobStatus.COMPLETED,
        JobStatus.ERROR,
        JobStatus.CANCEL_REQUESTED,
        JobStatus.CANCELED,
        JobStatus.PAUSED,
    }


def test_suite_type_has_three_kinds():
    assert set(SuiteType) == {SuiteType.REGULAR, SuiteType.MONITOR, SuiteType.CONTRACT}


def test_a_contract_is_neither_regular_nor_monitor():
    # Every regular-test read path filters `== SuiteType.REGULAR` and every monitor branch
    # asks `== SuiteType.MONITOR`. A contract suite must satisfy neither, or it surfaces as
    # one of the two kinds that already have screens.
    assert SuiteType.CONTRACT != SuiteType.REGULAR
    assert SuiteType.CONTRACT != SuiteType.MONITOR
    assert SuiteType.CONTRACT == "contract"
