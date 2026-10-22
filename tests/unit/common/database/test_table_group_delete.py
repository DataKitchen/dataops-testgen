"""Guards on deleting a table group, which run before anything is deleted."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.database.table_group_service import DeleteBlocker, cascade_delete_table_group
from testgen.common.enums import JobKey, JobStatus

pytestmark = pytest.mark.unit

MODULE = "testgen.common.database.table_group_service"


def _table_group() -> MagicMock:
    return MagicMock(id=uuid4(), project_code="demo")


@pytest.fixture
def jobs():
    with (
        patch(f"{MODULE}._has_job_in_flight", return_value=False) as in_flight,
        patch(f"{MODULE}.JobExecution") as job_execution,
        patch(f"{MODULE}.TableGroup") as table_group_cls,
    ):
        job_execution.cancel_queued_catalog_refreshes.return_value = True
        yield in_flight, job_execution, table_group_cls


def test_an_idle_table_group_is_deleted(jobs):
    in_flight, job_execution, table_group_cls = jobs
    table_group = _table_group()

    assert cascade_delete_table_group(table_group) is None

    assert in_flight.call_args.args[0] is table_group
    job_execution.cancel_queued_catalog_refreshes.assert_called_once_with(table_group_cls, table_group.id)
    table_group_cls.cascade_delete.assert_called_once_with([str(table_group.id)])


def test_a_job_in_flight_blocks_the_delete_and_leaves_queued_refreshes_alone(jobs):
    """Canceling the queued refreshes is a write, so it waits until nothing else can refuse."""
    in_flight, job_execution, table_group_cls = jobs
    in_flight.return_value = True

    assert cascade_delete_table_group(_table_group()) == DeleteBlocker.JOB

    job_execution.cancel_queued_catalog_refreshes.assert_not_called()
    table_group_cls.cascade_delete.assert_not_called()


def test_a_started_catalog_refresh_blocks_the_delete(jobs):
    _, job_execution, table_group_cls = jobs
    job_execution.cancel_queued_catalog_refreshes.return_value = False

    assert cascade_delete_table_group(_table_group()) == DeleteBlocker.CATALOG_REFRESH

    table_group_cls.cascade_delete.assert_not_called()


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.JobExecution.cancel_queued_catalog_refreshes", return_value=True)
@patch(f"{MODULE}.get_current_session")
def test_queued_jobs_block_the_delete_and_catalog_refreshes_are_left_to_the_cancel(
    mock_session, _cancel, _table_group_cls,
):
    """A profiling or test run has no run row until a worker starts it, so the guard reads the job
    queue itself: a job submitted just before the delete has to count while it is still pending.
    Catalog refreshes are the one kind it leaves out, because the delete cancels those instead."""
    session = MagicMock()
    mock_session.return_value = session
    session.scalars.return_value.all.return_value = []
    session.scalars.return_value.first.return_value = uuid4()

    assert cascade_delete_table_group(_table_group()) == DeleteBlocker.JOB

    statement = session.scalars.call_args_list[-1].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    where = str(statement.whereclause.compile(dialect=postgresql.dialect()))
    assert "job_executions.job_key != " in where
    assert JobKey.refresh_data_catalog in compiled.params.values()
    statuses = next(value for value in compiled.params.values() if isinstance(value, list | tuple))
    assert JobStatus.PENDING in statuses
