import random
import typing
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

import streamlit as st
from sqlalchemy import select

from testgen.commands.run_observability_exporter import test_observability_exporter
from testgen.common.enums import JobKey, JobSource, JobStatus
from testgen.common.models import database_session, with_database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.project import Project
from testgen.common.models.scheduler import (
    DEFAULT_DATA_CLEANUP_CRON,
    DEFAULT_RETENTION_CRON_TZ,
    JobSchedule,
)
from testgen.common.models.test_run import TestRun
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services.query_cache import get_project, select_projects_where
from testgen.ui.session import session, temp_value
from testgen.ui.utils import get_cron_sample_handler

DEFAULT_RETENTION_DAYS = 180

PAGE_TITLE = "Project Settings"


class ProjectSettingsPage(Page):
    path = "settings"
    permission = "administer"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon="settings",
        label=PAGE_TITLE,
        section="Settings",
        order=0,
    )

    project: Project | None = None
    existing_names: list[str] | None = None

    def render(self, project_code: str | None = None, **_kwargs) -> None:
        self.project = get_project(project_code)
        retention_schedule = JobSchedule.get(
            JobSchedule.project_code == project_code,
            JobSchedule.key == JobKey.run_data_cleanup,
        )
        retention_last_run = self._get_last_cleanup_timestamp(project_code)

        testgen.page_header(
            PAGE_TITLE,
            "manage-projects/",
        )

        get_test_results, set_test_results = temp_value(f"project_settings:{project_code}", default=None)
        cron_sample_result, on_cron_sample = get_cron_sample_handler(
            f"project_settings:cron_sample:{project_code}", sample_count=2,
        )
        # Persistent session_state (not pop-on-read) so rapid days edits don't lose the response.
        retention_preview_key = f"project_settings:retention_preview:{project_code}"

        def on_observability_connection_test(payload: dict) -> None:
            results = self.test_observability_connection(project_code, payload)
            set_test_results(asdict(results))

        def on_retention_preview(payload: dict) -> None:
            st.session_state[retention_preview_key] = self._get_retention_preview(
                project_code, payload.get("retention_days"),
            )

        return testgen.project_settings(
            key="project_settings",
            data={
                "name": self.project.project_name,
                "use_dq_score_weights": self.project.use_dq_score_weights,
                "observability_api_url": self.project.observability_api_url,
                "observability_api_key": self.project.observability_api_key,
                "observability_test_results": get_test_results(),
                "data_retention_enabled": self.project.data_retention_enabled,
                "data_retention_days": self.project.data_retention_days or DEFAULT_RETENTION_DAYS,
                "retention_cron_expr": retention_schedule.cron_expr if retention_schedule else DEFAULT_DATA_CLEANUP_CRON,
                "retention_cron_tz": retention_schedule.cron_tz if retention_schedule else None,
                "retention_cron_sample": cron_sample_result(),
                "retention_last_run": int(retention_last_run.timestamp() * 1000) if retention_last_run else None,
                "retention_preview": st.session_state.get(retention_preview_key),
            },
            on_TestObservabilityClicked_change=on_observability_connection_test,
            on_GetCronSample_change=on_cron_sample,
            on_GetRetentionPreview_change=on_retention_preview,
            on_SaveClicked_change=lambda payload: self.update_project(project_code, payload),
        )

    @staticmethod
    def _get_last_cleanup_timestamp(project_code: str) -> datetime | None:
        with database_session() as session_:
            return session_.scalar(
                select(JobExecution.completed_at)
                .where(
                    JobExecution.project_code == project_code,
                    JobExecution.job_key == JobKey.run_data_cleanup,
                    JobExecution.status == JobStatus.COMPLETED,
                    JobExecution.completed_at.isnot(None),
                )
                .order_by(JobExecution.completed_at.desc())
                .limit(1)
            )

    @staticmethod
    def _get_retention_preview(project_code: str, retention_days: int | None) -> dict | None:
        if not retention_days or retention_days < 1:
            return None
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        with database_session():
            protected_profiling_ids = ProfilingRun.find_latest_per_table_group(project_code)
            protected_test_ids = TestRun.find_latest_per_test_suite(project_code)
            return {
                "profiling_count": ProfilingRun.delete_older_than(
                    cutoff, project_code, protected_profiling_ids, dry_run=True,
                ),
                "test_count": TestRun.delete_older_than(
                    cutoff, project_code, protected_test_ids, dry_run=True,
                ),
                # Tiebreaker: identical counts for different days otherwise deep-equal and suppress the prop update.
                "_": random.random(),  # noqa: S311
            }

    @with_database_session
    def update_project(self, project_code: str, edited_project: dict) -> None:
        existing_names = [
            p.project_name.lower() for p in select_projects_where(Project.project_code != project_code)
        ]
        new_project_name = edited_project["name"]
        if new_project_name.lower() in existing_names:
            raise ValueError(f"Another project named {new_project_name} exists")

        weights_changed = self.project.use_dq_score_weights != edited_project.get("use_dq_score_weights", True)

        self.project.project_name = new_project_name
        self.project.use_dq_score_weights = edited_project.get("use_dq_score_weights", True)
        self.project.observability_api_url = edited_project.get("observability_api_url")
        self.project.observability_api_key = edited_project.get("observability_api_key")

        retention_enabled = bool(edited_project.get("data_retention_enabled"))
        retention_days = edited_project.get("data_retention_days") or DEFAULT_RETENTION_DAYS
        self.project.data_retention_enabled = retention_enabled
        self.project.data_retention_days = retention_days if retention_enabled else None
        self.project.save()
        get_project.clear()
        select_projects_where.clear()

        if retention_enabled:
            JobSchedule.upsert_for_retention(
                project_code=project_code,
                retention_days=retention_days,
                cron_expr=edited_project.get("retention_cron_expr") or DEFAULT_DATA_CLEANUP_CRON,
                cron_tz=edited_project.get("retention_cron_tz") or DEFAULT_RETENTION_CRON_TZ,
            )
        else:
            JobSchedule.delete_for_retention(project_code)

        if weights_changed:
            JobExecution.submit(
                job_key=JobKey.recalculate_project_scores,
                kwargs={"project_code": project_code},
                source=JobSource.ui,
                project_code=project_code,
            )
            st.toast("Scores will be recalculated in the background.")

        st.toast("Project settings saved", icon=":material/task_alt:")

    def test_observability_connection(self, project_code: str, edited_project: dict) -> "ObservabilityConnectionStatus":
        try:
            test_observability_exporter(
                project_code,
                edited_project.get("observability_api_url"),
                edited_project.get("observability_api_key"),
            )
            return ObservabilityConnectionStatus(successful=True, message="The connection was successful.")
        except Exception as e:
            error_message = e.args[0]
            return ObservabilityConnectionStatus(
                successful=False,
                message="Error attempting the connection",
                details=error_message,
            )


@dataclass(frozen=True, slots=True)
class ObservabilityConnectionStatus:
    message: str
    successful: bool
    details: str | None = field(default=None)
    _: float = field(default_factory=random.random)
