import signal
import threading
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from testgen import settings
from testgen.commands.job_registry import JobConfig
from testgen.common.enums import JobKey, JobSource
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.scheduler import JobSchedule
from testgen.scheduler.base import DelayedPolicy
from testgen.scheduler.cli_scheduler import CliJob, CliScheduler, _run_final_callbacks_for, run_scheduler

pytestmark = pytest.mark.unit


@pytest.fixture
def scheduler_instance() -> CliScheduler:
    with patch("testgen.scheduler.cli_scheduler.threading.Timer"):
        yield CliScheduler()


@pytest.fixture
def db_jobs(scheduler_instance):
    with (
        patch("testgen.scheduler.cli_scheduler.JobSchedule.select_runnable") as mock,
    ):
        yield mock


@pytest.fixture
def job_data():
    with patch.dict("testgen.commands.job_registry.JOB_DISPATCH", {"test-job": JobConfig(handler=Mock())}):
        yield {
            "cron_expr": "*/5 9-17 * * *",
            "cron_tz":  "UTC",
            "key":  "test-job",
            "kwargs":  {"b": "c"},
        }


@pytest.fixture
def job_sched(job_data):
    yield JobSchedule(**job_data)


@pytest.fixture
def cli_job(job_data):
    yield CliJob(**job_data, delayed_policy=DelayedPolicy.SKIP)


def test_get_jobs(scheduler_instance, db_jobs, job_sched):
    db_jobs.return_value = iter([job_sched])

    jobs = list(scheduler_instance.get_jobs())

    assert len(jobs) == 1
    assert isinstance(jobs[0], CliJob)
    for attr in ("cron_expr", "cron_tz", "key", "kwargs"):
        assert getattr(jobs[0], attr) == getattr(job_sched, attr), f"Attribute '{attr}' does not match"


def test_job_start(scheduler_instance, cli_job):
    mock_session = MagicMock()
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    with patch("testgen.common.models.Session", return_value=mock_session):
        scheduler_instance.start_job(cli_job, datetime.now(UTC))

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.job_key == cli_job.key
    assert added.kwargs == cli_job.kwargs
    assert added.source == "scheduler"
    assert added.job_schedule_id == cli_job.job_schedule_id
    mock_session.commit.assert_called_once()


def test_job_start_tags_source_from_job_config(scheduler_instance, job_data):
    """Scheduled executions inherit `JobConfig.scheduler_source` as their
    `JobExecution.source`. Retention cleanup (registered with
    `scheduler_source="system"`) gets `source="system"` so MCP / REST /
    api/deps filters auto-hide it from user-facing surfaces."""
    from testgen.scheduler.cli_scheduler import CliJob

    system_job_data = {**job_data, "key": JobKey.run_data_cleanup}
    system_cli_job = CliJob(**system_job_data, delayed_policy=DelayedPolicy.SKIP)

    mock_session = MagicMock()
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    with (
        patch.dict(
            "testgen.commands.job_registry.JOB_DISPATCH",
            {JobKey.run_data_cleanup: JobConfig(handler=Mock(), scheduler_source=JobSource.system)},
        ),
        patch("testgen.common.models.Session", return_value=mock_session),
    ):
        scheduler_instance.start_job(system_cli_job, datetime.now(UTC))

    added = mock_session.add.call_args[0][0]
    assert added.source == "system"


def test_shutdown_no_jobs(scheduler_instance):
    with (
        patch.object(scheduler_instance, "start") as start_mock,
        patch.object(scheduler_instance, "shutdown") as shutdown_mock,
        patch.object(scheduler_instance, "wait") as wait_mock,
        patch("testgen.scheduler.cli_scheduler.signal.signal") as signal_mock,
    ):
        start_called = threading.Event()
        start_mock.side_effect = lambda *_: start_called.set()

        thread = threading.Thread(target=scheduler_instance.run)
        thread.start()

        start_called.wait()
        sig_hanlder = signal_mock.call_args[0][1]
        shutdown_mock.assert_not_called()

        sig_hanlder(15, None)

        thread.join()

        shutdown_mock.assert_called_once()
        wait_mock.assert_called_once()
        assert not scheduler_instance.executor._running_jobs


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_shutdown(scheduler_instance, sig):
    with (
        patch.object(scheduler_instance, "start") as start_mock,
        patch.object(scheduler_instance, "shutdown") as shutdown_mock,
        patch.object(scheduler_instance, "wait") as wait_mock,
        # Covered on its own below; here it would only reach for a database.
        patch.object(scheduler_instance.executor, "_request_interrupt_on_running_jobs", return_value=set()),
        patch("testgen.scheduler.cli_scheduler.signal.signal") as signal_mock,
    ):
        start_called = threading.Event()
        start_mock.side_effect = lambda *_: start_called.set()

        procs = [MagicMock() for _ in range(5)]

        thread = threading.Thread(target=scheduler_instance.run)
        thread.start()

        start_called.wait()
        sig_handler = signal_mock.call_args[0][1]
        shutdown_mock.assert_not_called()

        for proc in procs:
            scheduler_instance.executor._running_jobs[uuid4()] = proc

        for send_sig_count in range(3):
            sig_handler(sig, None)
            time.sleep(0.05)
            for proc in procs:
                assert proc.send_signal.call_count == send_sig_count
                if send_sig_count:
                    proc.send_signal.assert_called_with(sig)

        scheduler_instance.executor._running_jobs.clear()
        with scheduler_instance.executor._running_jobs_cond:
            scheduler_instance.executor._running_jobs_cond.notify()

        thread.join()

        shutdown_mock.assert_called_once()
        wait_mock.assert_called_once()
        assert not scheduler_instance.executor._running_jobs


def test_the_shutdown_wait_is_bounded(scheduler_instance):
    """Waiting past the runtime's stop grace period gets the whole container killed, so a job
    that will not stop must cost the scheduler its deadline, not its clean exit."""
    with patch.object(scheduler_instance.executor, "_running_jobs_cond") as cond:
        cond.__enter__ = Mock(return_value=cond)
        cond.__exit__ = Mock(return_value=False)
        cond.wait_for.return_value = False
        scheduler_instance.executor._running_jobs[uuid4()] = MagicMock()
        with (
            patch.object(scheduler_instance, "start"),
            patch.object(scheduler_instance, "shutdown"),
            patch.object(scheduler_instance, "wait"),
            patch.object(scheduler_instance.executor, "_request_interrupt_on_running_jobs", return_value=set()),
            patch("testgen.scheduler.cli_scheduler.signal.signal"),
            patch("testgen.scheduler.cli_scheduler.threading.Event") as event,
        ):
            event.return_value.wait.return_value = None
            scheduler_instance.run()

    assert cond.wait_for.call_args.kwargs["timeout"] == settings.JOB_SHUTDOWN_TIMEOUT


def test_run_scheduler_settles_stale_jobs_before_starting(scheduler_db_session):
    with (
        patch("testgen.scheduler.cli_scheduler.check_db_is_ready", return_value=True),
        patch.object(JobExecution, "recover_stale", return_value=set()) as recover,
        patch("testgen.scheduler.cli_scheduler.CliScheduler") as scheduler_cls,
    ):
        run_scheduler()

    recover.assert_called_once()
    scheduler_cls.return_value.run.assert_called_once()


def test_run_scheduler_fires_final_callbacks_for_the_runs_a_restart_ended(scheduler_db_session):
    """Those runs reached a final status, so they notify like any other run that failed. Off the
    startup path, so a slow delivery does not hold back the scheduler."""
    failed = {uuid4(), uuid4()}
    rows = {job_id: MagicMock(id=job_id) for job_id in failed}
    with (
        patch("testgen.scheduler.cli_scheduler.check_db_is_ready", return_value=True),
        patch.object(JobExecution, "recover_stale", return_value=failed),
        patch.object(JobExecution, "get", side_effect=rows.get),
        patch("testgen.scheduler.cli_scheduler.run_final_callbacks") as callbacks,
        patch("testgen.scheduler.cli_scheduler.threading.Thread") as thread,
        patch("testgen.scheduler.cli_scheduler.CliScheduler") as scheduler_cls,
    ):
        run_scheduler()
        callbacks.assert_not_called()
        thread.return_value.start.assert_called_once()
        scheduler_cls.return_value.run.assert_called_once()

        thread.call_args.kwargs["target"](*thread.call_args.kwargs["args"])

    assert {call.args[0].id for call in callbacks.call_args_list} == failed


def test_a_restart_ended_run_that_cannot_be_read_does_not_stop_the_others(scheduler_db_session):
    unreadable, deleted, readable = uuid4(), uuid4(), uuid4()
    row = MagicMock(id=readable)

    def get(job_id):
        if job_id == unreadable:
            raise RuntimeError("connection reset")
        return row if job_id == readable else None

    with (
        patch.object(JobExecution, "get", side_effect=get),
        patch("testgen.scheduler.cli_scheduler.run_final_callbacks") as callbacks,
    ):
        _run_final_callbacks_for([unreadable, deleted, readable])

    callbacks.assert_called_once_with(row)


@pytest.mark.parametrize(
    ("revision_check", "ready"),
    [
        ({"return_value": True}, True),
        ({"return_value": False}, False),
        ({"side_effect": RuntimeError('relation "tg_revision" does not exist')}, False),
    ],
)
def test_the_scheduler_starts_only_on_a_schema_this_version_matches(revision_check, ready):
    from testgen.scheduler.cli_scheduler import check_db_is_ready

    with patch("testgen.scheduler.cli_scheduler.is_db_revision_up_to_date", **revision_check):
        assert check_db_is_ready() is ready


def test_the_scheduler_waits_for_the_upgrade_instead_of_exiting(scheduler_db_session):
    with (
        patch("testgen.scheduler.cli_scheduler.is_db_revision_up_to_date", side_effect=[False, False, True]),
        patch("testgen.scheduler.cli_scheduler.time.sleep") as sleep,
        patch.object(JobExecution, "recover_stale", return_value=set()) as recover,
        patch("testgen.scheduler.cli_scheduler.CliScheduler"),
    ):
        run_scheduler()

    assert sleep.call_count == 2
    recover.assert_called_once()



@pytest.fixture
def scheduler_db_session():
    """Patch the scheduler module's session context manager, yielding a mock session."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = Mock(return_value=session)
    ctx.__exit__ = Mock(return_value=False)
    with patch("testgen.scheduler.cli_scheduler.database_session", return_value=ctx):
        yield session


def test_start_job_submits_execution(scheduler_instance):
    from testgen.scheduler.base import DelayedPolicy
    from testgen.scheduler.cli_scheduler import CliJob

    schedule_id = uuid4()
    job = CliJob(
        cron_expr="*/5 * * * *",
        cron_tz="UTC",
        delayed_policy=DelayedPolicy.SKIP,
        key=JobKey.run_profile,
        kwargs={"table_group_id": "tg-123"},
        job_schedule_id=schedule_id,
    )

    mock_session = MagicMock()
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=False)
    with patch("testgen.common.models.Session", return_value=mock_session):
        scheduler_instance.start_job(job, datetime.now(UTC))

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.job_key == JobKey.run_profile
    assert added.kwargs == {"table_group_id": "tg-123"}
    assert added.source == "scheduler"
    assert added.job_schedule_id == schedule_id
    mock_session.commit.assert_called_once()


def test_the_scheduler_drives_its_executor(scheduler_instance):
    """The poll loop stops on the executor's own flag, so a shutdown that skipped it would leave
    the poll thread claiming jobs and the join in wait() hanging."""
    executor = scheduler_instance.executor
    with (
        patch.object(executor, "start") as start,
        patch.object(executor, "wait") as wait,
        patch("testgen.scheduler.base.threading.Thread"),
    ):
        scheduler_instance.start(datetime.now(UTC))
        start.assert_called_once_with()
        assert not executor._stopping.is_set()

        scheduler_instance.shutdown()
        assert executor._stopping.is_set()
        assert scheduler_instance._stopping.is_set()

        scheduler_instance.wait(3)
        wait.assert_called_once_with(3)


def test_a_failed_start_still_stops_the_executor(scheduler_instance):
    """The poll thread is not a daemon, so an executor left running keeps the process alive."""
    executor = scheduler_instance.executor
    with (
        patch.object(scheduler_instance, "start", side_effect=RuntimeError("boom")),
        patch.object(executor, "drain"),
        patch("testgen.scheduler.cli_scheduler.signal.signal"),
        pytest.raises(RuntimeError),
    ):
        scheduler_instance.run()

    assert executor._stopping.is_set()
