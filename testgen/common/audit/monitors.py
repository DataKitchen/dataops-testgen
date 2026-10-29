from testgen.common.audit.actions import AuditAction, AuditTargetType
from testgen.common.audit.recorder import changes_of, record
from testgen.common.audit.safety import never_raises
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.test_suite import MONITOR_SETTING_DEFAULTS, TestSuite

_SETTINGS = tuple(MONITOR_SETTING_DEFAULTS)
_TIMING = ("cron_expr", "cron_tz")


@never_raises()
def record_monitoring_enabled(monitor_suite: TestSuite, schedule: JobSchedule | None = None) -> None:
    """Record monitoring turned on: ``monitor_suite`` with its settings and its schedule's timing and state.

    :param schedule: the suite's schedule; looked up when not given.
    """
    schedule = schedule or _schedule_of(monitor_suite)
    changes = changes_of(monitor_suite, only=_SETTINGS)
    if schedule:
        changes |= changes_of(schedule, only=(*_TIMING, "active"))
    _record(AuditAction.MONITOR_SUITE_CREATED, monitor_suite, changes)


@never_raises()
def record_monitoring_updated(monitor_suite: TestSuite, schedule: JobSchedule) -> None:
    """Record the changes to ``monitor_suite``'s settings and its schedule's timing, then a pause or resume of the
    schedule on its own.
    """
    changes = changes_of(monitor_suite, only=_SETTINGS) | changes_of(schedule, only=_TIMING)
    _record(AuditAction.MONITOR_SUITE_UPDATED, monitor_suite, changes)
    if "from" in changes_of(schedule, only=("active",)).get("active", {}):
        action = AuditAction.MONITOR_SUITE_RESUMED if schedule.active else AuditAction.MONITOR_SUITE_PAUSED
        _record(action, monitor_suite, {})


@never_raises()
def record_monitoring_deleted(monitor_suite: TestSuite) -> None:
    """Record ``monitor_suite`` deleted, with its monitors, their history, and its schedule."""
    _record(AuditAction.MONITOR_SUITE_DELETED, monitor_suite, {})


@never_raises()
def _schedule_of(monitor_suite: TestSuite) -> JobSchedule | None:
    return JobSchedule.get_for_monitor_suite(monitor_suite.id)


def _record(action: AuditAction, monitor_suite: TestSuite, changes: dict) -> None:
    record(action, monitor_suite, target_type=AuditTargetType.MONITOR_SUITE, changes=changes)
