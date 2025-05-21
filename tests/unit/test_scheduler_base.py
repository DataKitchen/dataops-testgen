import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import islice
from unittest.mock import Mock, patch

import pytest

from testgen.scheduler.base import DelayedPolicy, Job, Scheduler


@contextmanager
def assert_finishes_within(**kwargs):
    start = datetime.now()
    yield
    assert datetime.now() < start + timedelta(**kwargs), f"Code block took more than {kwargs!s} to complete"


@pytest.fixture
def scheduler_instance() -> Scheduler:
    class TestScheduler(Scheduler):
        get_jobs = Mock()
        start_job = Mock()

    yield TestScheduler()


@pytest.fixture
def no_wait(scheduler_instance):
    mock = Mock(side_effect=lambda _: not scheduler_instance._reload_event.is_set())
    with patch.object(scheduler_instance, "_wait_until", mock):
        yield mock


@pytest.fixture
def base_time(scheduler_instance):
    dt = datetime(2025, 4, 15, 9, 0, 0, tzinfo=UTC)
    with patch.object(scheduler_instance, "base_time", dt):
        yield dt


@pytest.fixture
def now_5_min_ahead(scheduler_instance, base_time):
    now = scheduler_instance.base_time + timedelta(minutes=5)
    def now_func():
        return max(scheduler_instance.base_time, now)
    with patch.object(scheduler_instance, "_get_now", now_func):
        yield now_func


@pytest.mark.unit
def test_getting_jobs_wont_crash(scheduler_instance, base_time):
    scheduler_instance.get_jobs.side_effect = Exception
    scheduler_instance.start(base_time)

    time.sleep(0.05)
    assert scheduler_instance.thread.is_alive()
    assert not scheduler_instance._reload_event.is_set()

    scheduler_instance.shutdown()
    scheduler_instance.wait()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("expr", "dpol", "expected_minutes"),
    [
        ("* * * * *", DelayedPolicy.ALL, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),
        ("* * * * *", DelayedPolicy.ONCE, [0, 5, 6, 7, 8, 9, 10, 11, 12, 13]),
        ("* * * * *", DelayedPolicy.SKIP, [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]),
    ])
def test_delayed_jobs_policies(expr, dpol, expected_minutes, scheduler_instance, base_time, now_5_min_ahead):
    scheduler_instance.get_jobs.return_value = [Job(cron_expr=expr, cron_tz="UTC", delayed_policy=dpol)]
    triggering_times = [tt for tt, jobs in islice(scheduler_instance._get_next_jobs(), 10)]
    expected_triggering_times = [base_time + timedelta(minutes=m) for m in expected_minutes]
    assert triggering_times == expected_triggering_times


@pytest.mark.unit
def test_jobs_start_in_order(scheduler_instance, base_time):
    jobs = {
        3: Job(cron_expr="*/3 * * * *", cron_tz="UTC", delayed_policy=DelayedPolicy.ALL),
        2: Job(cron_expr="*/2 * * * *", cron_tz="UTC", delayed_policy=DelayedPolicy.ALL),
        4: Job(cron_expr="*/4 * * * *", cron_tz="UTC", delayed_policy=DelayedPolicy.ALL),
        5: Job(cron_expr="*/5 * * * *", cron_tz="UTC", delayed_policy=DelayedPolicy.ALL),
    }

    scheduler_instance.get_jobs.return_value = list(jobs.values())
    next_jobs = scheduler_instance._get_next_jobs()

    for triggering_time, triggred_jobs in islice(next_jobs, 12):
        for divisor, job in jobs.items():
            assert job not in triggred_jobs or triggering_time.minute % divisor == 0
            assert job in triggred_jobs or triggering_time.minute % divisor != 0


@pytest.mark.unit
@pytest.mark.parametrize("with_job", (True, False))
def test_reloads_and_shutdowns_immediately(with_job, scheduler_instance, base_time):
    jobs = [Job(cron_expr="0 0 * * *", cron_tz="UTC", delayed_policy=DelayedPolicy.ALL)] if with_job else []
    scheduler_instance.get_jobs.return_value = jobs

    scheduler_instance.start(base_time)
    time.sleep(0.05)
    assert scheduler_instance.get_jobs.call_count == 1
    with assert_finishes_within(milliseconds=100):
        scheduler_instance.reload_jobs()
        time.sleep(0.05)
        assert scheduler_instance.get_jobs.call_count == 2
        scheduler_instance.shutdown()
        scheduler_instance.wait()


@pytest.mark.unit
@pytest.mark.parametrize("start_side_effect", (lambda *_: None, Exception))
def test_job_start_is_called(start_side_effect, scheduler_instance, base_time, no_wait):
    jobs = [
        Job(cron_expr="* * * * *", cron_tz="UTC", delayed_policy=DelayedPolicy.ALL),
        Job(cron_expr="*/2 * * * *", cron_tz="UTC", delayed_policy=DelayedPolicy.ALL),
    ]
    scheduler_instance.get_jobs.side_effect = lambda: iter(jobs)
    scheduler_instance.start_job.side_effect = start_side_effect
    with (
        patch.object(
            scheduler_instance,
            "_get_next_jobs",
            side_effect=lambda: islice(Scheduler._get_next_jobs(scheduler_instance), 4),
        ) as get_next_mock,
    ):
        scheduler_instance.start(base_time)

        for multiplier in (1, 2):
            while scheduler_instance.start_job.call_count != 6 * multiplier:
                time.sleep(0.01)

            assert scheduler_instance.get_jobs.call_count == multiplier
            assert get_next_mock.call_count == multiplier

            if multiplier == 1:
                scheduler_instance.reload_jobs()

        scheduler_instance.shutdown()
        scheduler_instance.wait()
