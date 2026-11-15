import logging
from datetime import UTC, datetime
from uuid import UUID

from testgen.commands.run_refresh_data_chars import run_data_chars_refresh
from testgen.commands.test_generation import run_monitor_generation
from testgen.common.audit.record import Actor
from testgen.common.audit.recorder import AuditContext, bind, current_context
from testgen.common.database.database_service import set_target_db_params
from testgen.common.enums import JobKey, JobSource
from testgen.common.job_context import job_context
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.models.user import User
from testgen.common.monitor_service import INITIAL_MONITOR_TYPES
from testgen.common.run_service import launch_run
from testgen.common.stoppable_job import Step, StoppableJob

LOG = logging.getLogger("testgen")


def submit_table_group_setup(
    table_group: TableGroup,
    source: JobSource,
    monitor_suite_id: UUID | None = None,
    run_profiling: bool = False,
) -> None:
    """Queue the catalog refresh and the setup steps that follow it for a saved table group.

    :param table_group: Saved table group.
    :param source: Who asked for the setup.
    :param monitor_suite_id: Monitor suite to generate the initial monitors for.
    :param run_profiling: Run profiling once the other steps are done.
    """
    if run_profiling and not monitor_suite_id:
        # Profiling refreshes the catalog itself.
        launch_run(
            job_key=JobKey.run_profile,
            kwargs={"table_group_id": str(table_group.id)},
            source=source,
            project_code=table_group.project_code,
        )
        return

    requester = current_context().actor if run_profiling else None
    JobExecution.submit(
        job_key=JobKey.refresh_data_catalog,
        kwargs={
            "table_group_id": str(table_group.id),
            "monitor_suite_id": str(monitor_suite_id) if monitor_suite_id else None,
            "run_profiling": run_profiling,
            **({"requested_by": str(requester.id)} if requester and requester.id else {}),
        },
        source=source,
        project_code=table_group.project_code,
    )


def run_catalog_refresh(
    table_group_id: str,
    monitor_suite_id: str | None = None,
    run_profiling: bool = False,
    requested_by: str | None = None,
) -> None:
    """Refresh a table group's data catalog, then run the setup steps that read it.

    :param table_group_id: Table group whose catalog is refreshed.
    :param monitor_suite_id: Monitor suite to generate the initial monitors for once the catalog is written.
    :param run_profiling: Submit a profiling run for the table group after the other steps.
    :param requested_by: Id of the user who asked for the setup, to whom the profiling run's launch is attributed.
    :raises Exception: The first error from the refresh or the monitor generation, re-raised once the other steps
        have run.
    """
    CatalogRefreshJob(table_group_id, monitor_suite_id, run_profiling, requested_by).execute()


class CatalogRefreshJob(StoppableJob[int]):
    """Refresh a table group's data catalog, generate its initial monitors, and queue its profiling run.

    A failed refresh or monitor generation does not stop the steps after it; the first error is
    raised once they have run.
    """

    def __init__(
        self,
        table_group_id: str,
        monitor_suite_id: str | None = None,
        run_profiling: bool = False,
        requested_by: str | None = None,
    ) -> None:
        super().__init__(job_context.get().job_id)
        self.table_group_id = table_group_id
        self.monitor_suite_id = monitor_suite_id
        self.run_profiling = run_profiling
        self.requested_by = requested_by
        self.first_error: Exception | None = None

    def execute(self) -> None:
        self.table_group = TableGroup.get(self.table_group_id)
        if self.table_group is None:
            LOG.info(f"Skipping data catalog refresh: table group {self.table_group_id} no longer exists")
            return
        super().execute()
        if self.first_error:
            raise self.first_error

    def on_start(self) -> None:
        self.connection = Connection.get(self.table_group.connection_id)
        set_target_db_params(self.connection.__dict__, self.table_group)

    def _refresh_catalog(self) -> None:
        LOG.info(f"Refreshing data catalog for table group {self.table_group_id}")
        try:
            # Profiling refreshes the catalog in full, so the steps before it need only the tables and columns.
            run_data_chars_refresh(
                self, self.connection, self.table_group, datetime.now(UTC), count_rows=not self.run_profiling,
            )
        except Exception as error:
            # A refresh that fails on row counts has still written the catalog, and a profiling run
            # reports a target error to the user where this job's failure would go unseen.
            LOG.exception("Data catalog refresh encountered errors")
            self.first_error = error

    def _generate_monitors(self) -> None:
        if not self.monitor_suite_id:
            return
        if TestSuite.get(self.monitor_suite_id) is None:
            LOG.info(f"Skipping initial monitor generation: monitor suite {self.monitor_suite_id} no longer exists")
            return
        try:
            run_monitor_generation(self.monitor_suite_id, INITIAL_MONITOR_TYPES)
        except Exception as error:
            LOG.exception("Initial monitor generation encountered errors")
            get_current_session().rollback()
            self.first_error = self.first_error or error

    def _queue_profiling(self) -> None:
        if not self.run_profiling:
            return
        source = job_context.get().source
        bind(AuditContext(source=source, actor=_requester(self.requested_by)))
        launch_run(
            job_key=JobKey.run_profile,
            kwargs={"table_group_id": self.table_group_id},
            source=source,
            project_code=self.table_group.project_code,
        )
        get_current_session().commit()

    STEPS = (
        Step("refresh_catalog", _refresh_catalog),
        Step("generate_monitors", _generate_monitors),
        Step("queue_profiling", _queue_profiling),
    )


def _requester(user_id: str | None) -> Actor | None:
    if not user_id:
        return None
    user = get_current_session().get(User, UUID(user_id))
    return Actor.of(user) if user else Actor(id=UUID(user_id), username=None)
