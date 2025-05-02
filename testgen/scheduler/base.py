import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from zoneinfo import ZoneInfo

from cron_converter import Cron

MAX_WORKERS = 3

LOG = logging.getLogger("testgen")

class DelayedPolicy(Enum):
    SKIP = auto()
    ONCE = auto()
    ALL = auto()


@dataclass
class Job:
    cron_expr: str
    cron_tz: str
    delayed_policy: DelayedPolicy

    def get_triggering_times(self, base_time: datetime):
        cron = Cron(self.cron_expr)
        scheduler = cron.schedule(base_time.astimezone(ZoneInfo(self.cron_tz)))
        while True:
            yield scheduler.next()


class Scheduler:

    def __init__(self):
        self.base_time = None
        self._stopping = threading.Event()
        self._reload_event = threading.Event()
        self.thread: threading.Thread | None = None

    def get_jobs(self) -> Iterable[Job]:
        raise NotImplementedError

    def start_job(self, job: Job, triggering_time: datetime) -> None:
        raise NotImplementedError

    def reload_jobs(self):
        self._reload_event.set()

    def start(self, base_time: datetime):
        self.base_time = base_time

        if self.thread:
            raise RuntimeError("The scheduler can be started only once")
        self.thread = threading.Thread(target=self._run)
        self.thread.start()

    def shutdown(self):
        self._stopping.set()
        self._reload_event.set()

    def wait(self, timeout: float | None = None):
        self.thread.join(timeout=timeout)

    def _get_now(self):
        return datetime.now(UTC)

    def _get_next_jobs(self):

        job_list_head = []

        try:
            all_jobs = self.get_jobs()
        except Exception as e:
            LOG.error("Error obtaining jobs: %r", e)  # noqa: TRY400
        else:
            for job in all_jobs:
                gen = job.get_triggering_times(self.base_time)
                job_list_head.append((next(gen), gen, job))
        finally:
            self._reload_event.clear()

        while job_list_head and not self._stopping.is_set():

            job_list_head.sort(key=lambda t: t[0])
            jobs = []
            now = self._get_now()

            while True:
                triggering_time, gen, job = job_list_head.pop(0)

                next_trigger_time = next(gen)
                while job.delayed_policy in (DelayedPolicy.SKIP, DelayedPolicy.ONCE) and next_trigger_time < now:
                    next_trigger_time = next(gen)
                job_list_head.append((next_trigger_time, gen, job))

                if triggering_time >= now or job.delayed_policy in (DelayedPolicy.ALL, DelayedPolicy.ONCE):
                    jobs.append(job)

                if triggering_time < job_list_head[0][0]:
                    break

            if jobs:
                yield triggering_time, jobs

    def _wait_until(self, triggering_time: datetime):
        timeout = (triggering_time - datetime.now(UTC)).total_seconds()
        if timeout > 0:
            if self._reload_event.wait(timeout):
                return False
            else:
                return True
        else:
            return True

    def _run(self):
        while not self._stopping.is_set():
            next_jobs = self._get_next_jobs()

            while True:
                try:
                    triggering_time, jobs = next(next_jobs)
                except StopIteration:
                    self._reload_event.wait()
                    break

                if self._wait_until(triggering_time):
                    LOG.info("%d jobs to start at %s", len(jobs), triggering_time)
                    for job in jobs:
                        try:
                            self.start_job(job, triggering_time)
                        except Exception as e:
                            LOG.error("Error starting %r: %r", job, e)  # noqa: TRY400
                    self.base_time = triggering_time + timedelta(seconds=1)
                else:
                    break
