from typing import Any

from testgen.common.audit.actions import AuditAction, AuditTargetType
from testgen.common.audit.recorder import changes_of, record
from testgen.common.audit.safety import never_raises
from testgen.common.models.project import Project
from testgen.common.models.scheduler import JobSchedule

PROJECT_SECTIONS: dict[AuditTargetType, tuple[str, ...]] = {
    AuditTargetType.PROJECT_INFO: ("project_name", "use_dq_score_weights"),
    AuditTargetType.PROJECT_OBSERVABILITY: ("observability_api_url", "observability_api_key"),
    AuditTargetType.PROJECT_RETENTION: ("data_retention_enabled", "data_retention_days"),
}

_RETENTION_FIELDS = PROJECT_SECTIONS[AuditTargetType.PROJECT_RETENTION]


@never_raises()
def record_project_created(project: Project, retention_schedule: JobSchedule | None = None) -> None:
    """Record the creation of ``project``, with its retention settings whether set or defaulted.

    :param retention_schedule: the data cleanup schedule created with the project, if any.
    """
    changes = changes_of(project)
    for name in _RETENTION_FIELDS:
        if name not in changes and (value := getattr(project, name)) is not None:
            changes[name] = {"to": value}
    record(AuditAction.PROJECT_CREATED, project, changes=changes | _schedule_changes(retention_schedule))


@never_raises()
def record_project_updated(project: Project, retention_schedule: JobSchedule | None = None) -> None:
    """Record one update of ``project`` for each section of its settings that changed.

    :param retention_schedule: the data cleanup schedule the update created or changed, if any. Its timing is recorded
        with the retention section.
    """
    for section, names in PROJECT_SECTIONS.items():
        changes = changes_of(project, only=names)
        if section == AuditTargetType.PROJECT_RETENTION:
            changes |= _schedule_changes(retention_schedule)
        record(AuditAction.PROJECT_UPDATED, project, target_type=section, changes=changes)


def _schedule_changes(schedule: JobSchedule | None) -> dict[str, dict[str, Any]]:
    if schedule is None:
        return {}
    return {
        f"retention_{name}": entry
        for name, entry in changes_of(schedule, only=("cron_expr", "cron_tz")).items()
    }
