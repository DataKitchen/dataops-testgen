"""MCP write tools for projects.

Project creation and deletion live in the enterprise project-management plugin
(gated on ``global_admin``); editing a project's own settings is a per-project
``administer`` operation that ships in core. This module holds the latter.
"""

from __future__ import annotations

from typing import Any

from testgen.common.enums import JobKey, JobSource
from testgen.common.models import with_database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.project import Project
from testgen.common.models.scheduler import (
    DEFAULT_DATA_CLEANUP_CRON,
    DEFAULT_RETENTION_CRON_TZ,
    JobSchedule,
)
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    raise_validation_error,
    render_diff_table,
    resolve_project,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.MANAGE

DEFAULT_RETENTION_DAYS = 180


def _empty_to_none(value: str | None) -> str | None:
    return value if value else None


@with_database_session
@mcp_permission("administer")
def update_project(
    project_code: str,
    *,
    project_name: str | None = None,
    use_dq_score_weights: bool | None = None,
    observability_api_url: str | None = None,
    observability_api_key: str | None = None,
    data_retention_enabled: bool | None = None,
    data_retention_days: int | None = None,
    retention_cron_expr: str | None = None,
    retention_cron_tz: str | None = None,
) -> str:
    """Update a project's settings.

    Args:
        project_code: The project code, e.g. from `list_projects`.
        project_name: New display name.
        use_dq_score_weights: Whether quality scoring uses the configured weights.
            Changing this re-runs project-wide score recalculation in the background.
        observability_api_url: DataOps Observability API URL. Pass an empty string to clear.
        observability_api_key: DataOps Observability API key. Pass an empty string to clear.
            Never echoed back in tool output.
        data_retention_enabled: Whether old profiling and test history is automatically deleted.
        data_retention_days: How many days of history to keep (only when retention is enabled).
            Defaults to 180 when retention is enabled without specifying days.
        retention_cron_expr: Cron expression for the retention cleanup job
            (only when retention is enabled). Defaults to daily at 01:00.
        retention_cron_tz: Timezone for the retention cleanup cron
            (only when retention is enabled). Defaults to UTC.
    """
    supplied = {
        "project_name": project_name,
        "use_dq_score_weights": use_dq_score_weights,
        "observability_api_url": observability_api_url,
        "observability_api_key": observability_api_key,
        "data_retention_enabled": data_retention_enabled,
        "data_retention_days": data_retention_days,
        "retention_cron_expr": retention_cron_expr,
        "retention_cron_tz": retention_cron_tz,
    }
    if all(value is None for value in supplied.values()):
        raise MCPUserError("No fields supplied to update.")

    project = resolve_project(project_code)

    schedule = JobSchedule.get(
        JobSchedule.project_code == project_code,
        JobSchedule.key == JobKey.run_data_cleanup,
    )

    # Compute effective retention state from supplied args + current state. Errors below.
    effective_enabled = (
        data_retention_enabled if data_retention_enabled is not None else project.data_retention_enabled
    )
    effective_days = (
        data_retention_days if data_retention_days is not None else project.data_retention_days
    )
    # When retention is being newly enabled without explicit days, fall back to the system default.
    if effective_enabled and effective_days is None:
        effective_days = DEFAULT_RETENTION_DAYS

    # Validate field-by-field; surface all errors at once.
    errors: list[str] = []
    cleaned_name: str | None = None
    if project_name is not None:
        cleaned_name = project_name.strip()
        if not cleaned_name:
            errors.append("project_name: must not be empty.")

    if data_retention_days is not None and data_retention_days < 1:
        errors.append("data_retention_days: must be a positive integer.")

    # Setting retention schedule args only makes sense when retention will be enabled.
    if not effective_enabled:
        if data_retention_days is not None:
            errors.append("data_retention_days: cannot be set when data_retention_enabled is False.")
        if retention_cron_expr is not None:
            errors.append("retention_cron_expr: cannot be set when data_retention_enabled is False.")
        if retention_cron_tz is not None:
            errors.append("retention_cron_tz: cannot be set when data_retention_enabled is False.")

    if errors:
        raise_validation_error(errors, "Update rejected. No changes saved.")

    weights_were = project.use_dq_score_weights

    # Snapshot the editable surface (including schedule cron + tz, which live on JobSchedule).
    before = _snapshot(project, schedule)

    # Apply project changes.
    if cleaned_name is not None:
        project.project_name = cleaned_name
    if use_dq_score_weights is not None:
        project.use_dq_score_weights = use_dq_score_weights
    if observability_api_url is not None:
        project.observability_api_url = _empty_to_none(observability_api_url)
    if observability_api_key is not None:
        project.observability_api_key = _empty_to_none(observability_api_key)
    project.data_retention_enabled = effective_enabled
    project.data_retention_days = effective_days if effective_enabled else None

    # Compute the effective cron values now so the snapshot reflects what the schedule will be.
    schedule_supplied = any(
        v is not None
        for v in (data_retention_enabled, data_retention_days, retention_cron_expr, retention_cron_tz)
    )
    effective_cron_expr: str | None
    effective_cron_tz: str | None
    if effective_enabled:
        effective_cron_expr = (
            retention_cron_expr or (schedule.cron_expr if schedule else None) or DEFAULT_DATA_CLEANUP_CRON
        )
        effective_cron_tz = (
            retention_cron_tz or (schedule.cron_tz if schedule else None) or DEFAULT_RETENTION_CRON_TZ
        )
    else:
        effective_cron_expr = None
        effective_cron_tz = None

    after = _snapshot(
        project,
        _ScheduleSnapshot(cron_expr=effective_cron_expr, cron_tz=effective_cron_tz)
        if effective_enabled
        else None,
    )

    doc = MdDoc()
    doc.heading(1, f"Project `{project_code}` updated")

    rendered = render_diff_table(
        doc, before, after,
        attrs=_DIFF_ORDER, labels=_DIFF_LABELS, secret_attrs=_SECRET_ATTRS,
    )
    if not rendered:
        doc.text("No fields changed — supplied values matched the current state.")
        return doc.render()

    project.save()

    # Schedule side effects: only touch JobSchedule when a retention-related arg was supplied.
    if schedule_supplied:
        if effective_enabled:
            JobSchedule.upsert_for_retention(
                project_code=project_code,
                retention_days=effective_days,  # type: ignore[arg-type]
                cron_expr=effective_cron_expr,  # type: ignore[arg-type]
                cron_tz=effective_cron_tz,  # type: ignore[arg-type]
            )
        else:
            JobSchedule.delete_for_retention(project_code)

    # Weights side effect: submit a background recalculation job, same as the UI.
    if use_dq_score_weights is not None and use_dq_score_weights != weights_were:
        JobExecution.submit(
            job_key=JobKey.recalculate_project_scores,
            kwargs={"project_code": project_code},
            source=JobSource.mcp,
            project_code=project_code,
        )

    return doc.render()


class _ScheduleSnapshot:
    """Stand-in for a JobSchedule row, used while computing the post-update snapshot
    before any DB write has happened."""

    def __init__(self, cron_expr: str | None, cron_tz: str | None) -> None:
        self.cron_expr = cron_expr
        self.cron_tz = cron_tz


def _snapshot(project: Project, schedule: Any) -> dict[str, Any]:
    return {
        "project_name": project.project_name,
        "use_dq_score_weights": project.use_dq_score_weights,
        "observability_api_url": project.observability_api_url,
        "observability_api_key": project.observability_api_key,
        "data_retention_enabled": project.data_retention_enabled,
        "data_retention_days": project.data_retention_days,
        "retention_cron_expr": schedule.cron_expr if schedule is not None else None,
        "retention_cron_tz": schedule.cron_tz if schedule is not None else None,
    }


_DIFF_ORDER: tuple[str, ...] = (
    "project_name",
    "use_dq_score_weights",
    "observability_api_url",
    "observability_api_key",
    "data_retention_enabled",
    "data_retention_days",
    "retention_cron_expr",
    "retention_cron_tz",
)

_DIFF_LABELS: dict[str, str] = {
    "project_name": "Name",
    "use_dq_score_weights": "Weighted quality scoring",
    "observability_api_url": "DataOps Observability API URL",
    "observability_api_key": "DataOps Observability API key",
    "data_retention_enabled": "Data retention",
    "data_retention_days": "Retention days",
    "retention_cron_expr": "Retention cron expression",
    "retention_cron_tz": "Retention timezone",
}

_SECRET_ATTRS: frozenset[str] = frozenset({"observability_api_key"})
