"""Quick-start runs handlers directly, with no scheduler behind them."""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands.run_quick_start import _drain_queued_jobs, run_with_job_execution
from testgen.common.enums import JobSource, JobStatus
from testgen.common.models.job_execution import JobExecution

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_quick_start"
PROJECT = "DEFAULT"


class _Row:
    def __init__(self, job_key="run-monitor-generation", *, project_code=PROJECT,
                 source=JobSource.system, kwargs=None):
        self.id = uuid4()
        self.job_key = job_key
        self.project_code = project_code
        self.source = source
        self.kwargs = kwargs or {}
        self.status = JobStatus.PENDING
        self.error_message = None

    def claim(self):
        self.status = JobStatus.CLAIMED
        return True

    def mark_running(self):
        self.status = JobStatus.RUNNING
        return True

    def mark_completed(self):
        self.status = JobStatus.COMPLETED
        return True

    def mark_failed(self, message):
        self.status = JobStatus.ERROR
        self.error_message = message
        return True


def _queue(*rounds, seen=None, depth=None):
    """Serve each round of pending rows to one drain pass, then nothing.

    ``depth`` counts open session contexts, so a caller can assert what runs inside one.
    """
    remaining = list(rounds)

    def scalars(query):
        if seen is not None:
            seen.append(query)
        result = MagicMock()
        result.all.return_value = remaining.pop(0) if remaining else []
        return result

    def enter():
        if depth is not None:
            depth.append("enter")
        return session

    def exit_(*_):
        if depth is not None:
            depth.pop()
        return False

    session = MagicMock()
    session.scalars.side_effect = scalars
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(side_effect=enter)
    ctx.__exit__ = MagicMock(side_effect=exit_)
    return ctx


def _dispatch(handler):
    entry = MagicMock()
    entry.handler = handler
    return dict.fromkeys(("run-monitor-generation", "run-test-generation", "run-profile"), entry)


def test_a_queued_follow_up_runs_and_is_marked_completed():
    row = _Row(kwargs={"test_suite_id": "abc"})
    handler = MagicMock()
    with (
        patch(f"{MODULE}.database_session", return_value=_queue([row])),
        patch.object(JobExecution, "get") as je,
        patch(f"{MODULE}.JOB_DISPATCH", _dispatch(handler)),
    ):
        je.return_value = row
        _drain_queued_jobs()

    handler.assert_called_once_with(test_suite_id="abc")
    assert row.status == JobStatus.COMPLETED


def test_a_drained_handler_is_never_given_a_run_date():
    """run_with_job_execution passes run_date to the handler it calls directly; the generation
    handlers have no such parameter, so the drain must not copy that call shape."""
    handler = MagicMock()
    row = _Row(kwargs={"test_suite_id": "abc"})
    with (
        patch(f"{MODULE}.database_session", return_value=_queue([row])),
        patch.object(JobExecution, "get") as je,
        patch(f"{MODULE}.JOB_DISPATCH", _dispatch(handler)),
    ):
        je.return_value = row
        _drain_queued_jobs()

    assert "run_date" not in handler.call_args.kwargs


def test_a_drained_handler_runs_inside_a_session():
    """The generation handlers read entities off the current session rather than opening one,
    so calling them outside a session leaves get_current_session() returning None."""
    depth = []
    open_when_called = []
    row = _Row()
    handler = MagicMock(side_effect=lambda **_: open_when_called.append(len(depth)))
    with (
        patch(f"{MODULE}.database_session", return_value=_queue([row], depth=depth)),
        patch.object(JobExecution, "get") as je,
        patch(f"{MODULE}.JOB_DISPATCH", _dispatch(handler)),
    ):
        je.return_value = row
        _drain_queued_jobs()

    assert open_when_called == [1]


def test_the_drain_keeps_going_when_a_follow_up_fails():
    first, second = _Row(), _Row()
    handler = MagicMock(side_effect=[RuntimeError("nope"), None])
    with (
        patch(f"{MODULE}.database_session", return_value=_queue([first, second])),
        patch.object(JobExecution, "get") as je,
        patch(f"{MODULE}.JOB_DISPATCH", _dispatch(handler)),
    ):
        je.side_effect = lambda job_id: first if job_id == first.id else second
        _drain_queued_jobs()

    assert first.status == JobStatus.ERROR
    assert "nope" in first.error_message
    assert second.status == JobStatus.COMPLETED


def test_the_drain_loops_for_work_a_follow_up_queues_itself():
    first, second = _Row(), _Row()
    handler = MagicMock()
    with (
        patch(f"{MODULE}.database_session", return_value=_queue([first], [second])),
        patch.object(JobExecution, "get") as je,
        patch(f"{MODULE}.JOB_DISPATCH", _dispatch(handler)),
    ):
        je.side_effect = lambda job_id: first if job_id == first.id else second
        _drain_queued_jobs()

    assert handler.call_count == 2
    assert (first.status, second.status) == (JobStatus.COMPLETED, JobStatus.COMPLETED)


def test_the_claim_is_scoped_to_the_seeded_project_and_system_rows():
    """Seeding a database that has real queued work must not pick that work up."""
    queries = []
    with (
        patch(f"{MODULE}.database_session", return_value=_queue([], seen=queries)),
        patch.object(JobExecution, "get"),
        patch(f"{MODULE}.JOB_DISPATCH", _dispatch(MagicMock())),
    ):
        _drain_queued_jobs()

    sql = str(queries[0].compile(compile_kwargs={"literal_binds": True}))
    assert f"project_code = '{PROJECT}'" in sql
    assert f"source = '{JobSource.system.value}'" in sql
    assert f"status = '{JobStatus.PENDING.value}'" in sql


def test_follow_ups_are_drained_before_the_score_rollup():
    """Their rows are created during the parent run, so they precede the score update a real
    scheduler would enqueue from the final callback."""
    order = []
    with (
        patch(f"{MODULE}.database_session") as session,
        patch.object(JobExecution, "get"),
        patch(f"{MODULE}.JOB_DISPATCH", _dispatch(MagicMock())),
        patch(f"{MODULE}._drain_queued_jobs", side_effect=lambda: order.append("drain")),
        patch(f"{MODULE}.run_score_update", side_effect=lambda **_: order.append("score")),
        patch(f"{MODULE}.job_context"),
    ):
        session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        session.return_value.__exit__ = MagicMock(return_value=False)
        run_with_job_execution("run-profile", table_group_id=str(uuid4()))

    assert order == ["drain", "score"]


@contextmanager
def _seeded_run(row, handler):
    """Stand ``row`` in for the synthetic JE a quick-start run creates and closes out."""
    with (
        patch(f"{MODULE}.database_session") as session,
        patch(f"{MODULE}.JobExecution") as je_cls,
        patch(f"{MODULE}.JOB_DISPATCH", _dispatch(handler)),
        patch(f"{MODULE}._drain_queued_jobs"),
        patch(f"{MODULE}.run_score_update"),
        patch(f"{MODULE}.job_context"),
    ):
        session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        session.return_value.__exit__ = MagicMock(return_value=False)
        je_cls.return_value = row
        je_cls.get.return_value = row
        yield


def test_a_seeded_run_records_what_it_worked():
    """Nothing claims a quick-start row, so the accumulator that measures a real run never runs
    for it. The duration displays read that column alone, so a row left without one reports no
    duration at all -- which is how seeded demo runs came to show none."""
    row = _Row("run-profile")
    row.started_at = row.completed_at = row.active_seconds = None
    effective = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

    with _seeded_run(row, MagicMock()):
        run_with_job_execution("run-profile", run_date=effective, table_group_id=str(uuid4()))

    assert row.completed_at is not None, "a settled run has an end"
    assert row.active_seconds is not None, "a settled run has a worked time"
    # Backdated, so the end follows the chosen start rather than the wall clock.
    assert row.completed_at >= effective


def test_a_seeded_run_keeps_no_end_when_its_handler_raises():
    """The exception is what the caller acts on, and stamping an end would report the worked
    time of a seed that did not finish."""
    row = _Row("run-profile")
    row.started_at = row.completed_at = row.active_seconds = None
    handler = MagicMock(side_effect=RuntimeError("seed blew up"))

    with _seeded_run(row, handler), pytest.raises(RuntimeError):
        run_with_job_execution("run-profile", table_group_id=str(uuid4()))

    assert row.completed_at is None
    assert row.active_seconds is None
