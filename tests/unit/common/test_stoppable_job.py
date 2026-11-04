import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import JobStatus
from testgen.common.stoppable_job import JobStopped, Step, StoppableJob, StopReason, StopSignal

pytestmark = pytest.mark.unit

MODULE = "testgen.common.stoppable_job"


@pytest.fixture
def row():
    return SimpleNamespace(status=JobStatus.RUNNING)


@pytest.fixture(autouse=True)
def session(row):
    mock = MagicMock()
    mock.scalar.side_effect = lambda *_a, **_k: row.status
    with patch(f"{MODULE}.get_current_session", return_value=mock):
        yield mock


@pytest.fixture(autouse=True)
def cancel_statements():
    with patch(f"{MODULE}.cancel_target_statements") as cancel:
        yield cancel


class _Job(StoppableJob[int]):
    """Fans out over its keys, recording what it handled."""

    def __init__(self, keys, process=None, ttl=0.0):
        super().__init__(uuid4(), StopSignal(uuid4(), ttl=ttl))
        self.keys = keys
        self.process = process or (lambda key: key * 10)
        self.handled: list[int] = []
        self.ran: list[str] = []

    def _work(self) -> None:
        self.ran.append("work")
        self.fan_out(self.keys, lambda key: key, self.process, lambda outcome: self.handled.append(outcome.result))

    def _after(self) -> None:
        self.ran.append("after")

    STEPS = (Step("work", _work), Step("after", _after))


# ---- stop signal --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (JobStatus.CANCEL_REQUESTED, StopReason.CANCEL),
        (JobStatus.CANCELED, StopReason.CANCEL),
        (JobStatus.INTERRUPT_REQUESTED, StopReason.INTERRUPT),
        (JobStatus.INTERRUPTED, StopReason.INTERRUPT),
        (JobStatus.PAUSE_REQUESTED, StopReason.PAUSE),
        (JobStatus.PAUSED, StopReason.PAUSE),
    ],
)
def test_the_stop_signal_knows_why_the_run_was_asked_to_stop(row, status, reason):
    signal = StopSignal(uuid4(), ttl=0)
    row.status = status

    assert signal.check() is True
    assert signal.reason == reason


def test_a_running_job_is_not_stopped(row):
    assert StopSignal(uuid4(), ttl=0).check() is False


def test_a_job_with_no_id_never_reads_a_row(session):
    assert StopSignal(None, ttl=0).check() is False
    session.scalar.assert_not_called()


# ---- stopping ------------------------------------------------------------------------------


def test_a_run_that_is_not_stopped_runs_every_step():
    job = _Job([1, 2, 3])

    job.execute()

    assert sorted(job.handled) == [10, 20, 30]
    assert job.ran == ["work", "after"]


def test_a_stop_between_steps_runs_no_further_step(row):
    job = _Job([1])
    original = job._work

    def work_then_cancel():
        original()
        row.status = JobStatus.CANCEL_REQUESTED

    job.STEPS = (Step("work", lambda _job: work_then_cancel()), _Job.STEPS[1])

    with pytest.raises(JobStopped) as stopped:
        job.execute()

    assert stopped.value.reason == StopReason.CANCEL
    assert stopped.value.step == "after"
    assert job.ran == ["work"]


def test_a_cancel_while_every_worker_is_busy_cancels_their_statements(row, cancel_statements):
    """No outcome arrives while the workers wait on long statements, so the job notices the
    request while it waits, and cancels them rather than waiting them out."""
    release = threading.Event()
    cancel_statements.side_effect = release.set

    def process(key):
        row.status = JobStatus.CANCEL_REQUESTED
        release.wait(5)
        return key

    job = _Job([1, 2, 3, 4], process=process)

    with pytest.raises(JobStopped) as stopped:
        job.execute()

    assert stopped.value.reason == StopReason.CANCEL
    cancel_statements.assert_called_once()
    # The canceled statements' outcomes are never handled.
    assert job.handled == []
    assert job.ran == ["work"]


@pytest.mark.parametrize(
    ("status", "cancels"),
    [
        (JobStatus.CANCEL_REQUESTED, True),
        (JobStatus.INTERRUPT_REQUESTED, True),
        (JobStatus.PAUSE_REQUESTED, False),
    ],
)
def test_only_the_reasons_the_job_declares_cancel_its_statements(row, cancel_statements, status, cancels):
    row.status = status

    with pytest.raises(JobStopped):
        _Job([1]).execute()

    assert cancel_statements.called is cancels


def test_a_job_can_keep_its_statements_running_on_any_reason(row, cancel_statements):
    row.status = JobStatus.CANCEL_REQUESTED
    job = _Job([1])
    job.CANCELS_IN_FLIGHT_ON = frozenset()

    with pytest.raises(JobStopped):
        job.execute()

    cancel_statements.assert_not_called()


def test_a_stop_is_not_an_error_any_handler_can_swallow():
    assert not issubclass(JobStopped, Exception)


# ---- threaded fetch ------------------------------------------------------------------------


def test_fetch_threaded_returns_the_rows_and_the_errors_by_query():
    def fetch(query, _params, use_target_db):
        assert use_target_db
        if query == "bad":
            raise ValueError("no such table")
        return [{"query": query}]

    job = _Job([])
    job._step = Step("work", _Job._work)
    progress = []

    with patch(f"{MODULE}.fetch_dict_from_db", side_effect=fetch):
        rows, errors = job.fetch_threaded(
            [("a", None), ("bad", None), ("c", None)],
            use_target_db=True,
            on_progress=lambda p: progress.append((p["processed"], p["errors"], p["total"])),
        )

    assert sorted(row["query"] for row in rows) == ["a", "c"]
    assert list(errors) == [1]
    assert "no such table" in errors[1]
    assert progress[-1] == (3, 1, 3)


def test_fetch_threaded_reports_no_step_progress_or_step_errors():
    job = _Job([])
    job._step = Step("work", _Job._work)
    job.on_step_progress = MagicMock()

    with patch(f"{MODULE}.fetch_dict_from_db", side_effect=ValueError("boom")):
        _, errors = job.fetch_threaded([("a", None)])

    assert list(errors) == [0]
    job.on_step_progress.assert_not_called()
    assert job._step_errors == 0


def test_fetch_threaded_stops_the_job_when_asked(row):
    row.status = JobStatus.CANCEL_REQUESTED
    job = _Job([])
    job._step = Step("work", _Job._work)

    with patch(f"{MODULE}.fetch_dict_from_db") as fetch, pytest.raises(JobStopped):
        job.fetch_threaded([("a", None)])

    fetch.assert_not_called()
