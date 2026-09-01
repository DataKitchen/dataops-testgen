import pytest

from testgen.common.enums import INTERRUPT_STATUSES, JOB_STATUS_LABEL, JobStatus
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
    assert set(JobStatus.claimable()) == {JobStatus.PENDING, JobStatus.INTERRUPTED}
    assert JobStatus.claimable() == JobStatus.sources_for(JobStatus.CLAIMED)


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


def test_an_interrupted_row_can_be_marked_interrupted_again():
    """The engine settles the row itself, and exec_job re-marks it as a belt for a stop that
    unwound without settling. Without the self-loop that belt logs a failed transition."""
    assert JobStatus.INTERRUPTED in JobStatus.sources_for(JobStatus.INTERRUPTED)


def test_stale_recoverable_excludes_exactly_the_queued_statuses():
    # Everything else in active() implies a process that is now gone, so a restart settles it.
    assert set(JobStatus.stale_recoverable()) == set(JobStatus.active()) - {
        JobStatus.PENDING, JobStatus.INTERRUPTED,
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


def test_pause_statuses_are_entered_only_from_running_or_each_other():
    """Nothing derives the constant, so the graph is what keeps it honest."""
    for status in INTERRUPT_STATUSES:
        sources = set(JobStatus.sources_for(status))
        assert sources <= INTERRUPT_STATUSES | {JobStatus.RUNNING}, status


def test_no_pause_status_is_left_out_of_the_constant():
    """A status entered only from a pause status belongs in INTERRUPT_STATUSES too."""
    for status in set(JobStatus) - INTERRUPT_STATUSES:
        sources = set(JobStatus.sources_for(status))
        assert not sources or not sources <= INTERRUPT_STATUSES, status


def test_pause_statuses_are_not_part_of_the_ordinary_lifecycle():
    assert not INTERRUPT_STATUSES & {
        JobStatus.PENDING, JobStatus.CLAIMED, JobStatus.RUNNING,
        JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCEL_REQUESTED, JobStatus.CANCELED,
    }
