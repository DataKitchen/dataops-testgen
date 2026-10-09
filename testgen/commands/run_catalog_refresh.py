import logging
from datetime import UTC, datetime
from uuid import UUID

from testgen.commands.run_refresh_data_chars import run_data_chars_refresh
from testgen.commands.test_generation import run_monitor_generation
from testgen.common.database.database_service import set_target_db_params
from testgen.common.enums import JobKey, JobSource
from testgen.common.job_context import job_context
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.table_group import TableGroup
from testgen.common.monitor_service import INITIAL_MONITOR_TYPES

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
        JobExecution.submit(
            job_key=JobKey.run_profile,
            kwargs={"table_group_id": str(table_group.id)},
            source=source,
            project_code=table_group.project_code,
        )
        return

    JobExecution.submit(
        job_key=JobKey.refresh_data_catalog,
        kwargs={
            "table_group_id": str(table_group.id),
            "monitor_suite_id": str(monitor_suite_id) if monitor_suite_id else None,
            "run_profiling": run_profiling,
        },
        source=source,
        project_code=table_group.project_code,
    )


def run_catalog_refresh(table_group_id: str, monitor_suite_id: str | None = None, run_profiling: bool = False) -> None:
    """Refresh a table group's data catalog, then run the setup steps that read it.

    :param table_group_id: Table group whose catalog is refreshed.
    :param monitor_suite_id: Monitor suite to generate the initial monitors for once the catalog is written.
    :param run_profiling: Submit a profiling run for the table group after the other steps.
    :raises Exception: The first error from the refresh or the monitor generation, re-raised once the other steps
        have run.
    """
    table_group = TableGroup.get(table_group_id)
    if table_group is None:
        raise ValueError(f"Table group {table_group_id} not found")
    connection = Connection.get(table_group.connection_id)
    set_target_db_params(connection.__dict__, table_group)

    LOG.info(f"Refreshing data catalog for table group {table_group_id}")
    first_error: Exception | None = None
    try:
        run_data_chars_refresh(connection, table_group, datetime.now(UTC))
    except Exception as error:
        # A refresh that fails on row counts has still written the catalog, and a profiling run
        # reports a target error to the user where this job's failure would go unseen.
        LOG.exception("Data catalog refresh encountered errors")
        first_error = error

    if monitor_suite_id:
        try:
            run_monitor_generation(monitor_suite_id, INITIAL_MONITOR_TYPES)
        except Exception as error:
            LOG.exception("Initial monitor generation encountered errors")
            get_current_session().rollback()
            first_error = first_error or error

    if run_profiling:
        JobExecution.submit(
            job_key=JobKey.run_profile,
            kwargs={"table_group_id": table_group_id},
            source=job_context.get().source,
            project_code=table_group.project_code,
        )
        get_current_session().commit()

    if first_error:
        raise first_error
