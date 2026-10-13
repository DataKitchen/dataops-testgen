from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from testgen.commands.run_catalog_refresh import run_catalog_refresh, submit_table_group_setup
from testgen.common.enums import JobKey, JobSource
from testgen.common.monitor_service import INITIAL_MONITOR_TYPES

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_catalog_refresh"


def _table_group():
    return MagicMock(id=uuid4(), project_code="DEFAULT", connection_id=1)


@patch(f"{MODULE}.JobExecution.submit")
def test_setup_with_only_profiling_leaves_the_catalog_to_profiling(mock_submit):
    table_group = _table_group()

    submit_table_group_setup(table_group, JobSource.ui, run_profiling=True)

    mock_submit.assert_called_once_with(
        job_key=JobKey.run_profile,
        kwargs={"table_group_id": str(table_group.id)},
        source=JobSource.ui,
        project_code="DEFAULT",
    )


@pytest.mark.parametrize("run_profiling", [True, False])
@patch(f"{MODULE}.JobExecution.submit")
def test_setup_with_monitors_refreshes_the_catalog_first(mock_submit, run_profiling):
    table_group = _table_group()
    monitor_suite_id = uuid4()

    submit_table_group_setup(table_group, JobSource.ui, monitor_suite_id=monitor_suite_id, run_profiling=run_profiling)

    mock_submit.assert_called_once_with(
        job_key=JobKey.refresh_data_catalog,
        kwargs={
            "table_group_id": str(table_group.id),
            "monitor_suite_id": str(monitor_suite_id),
            "run_profiling": run_profiling,
        },
        source=JobSource.ui,
        project_code="DEFAULT",
    )


@patch(f"{MODULE}.JobExecution.submit")
def test_setup_without_follow_ups_still_refreshes_the_catalog(mock_submit):
    table_group = _table_group()

    submit_table_group_setup(table_group, JobSource.ui)

    assert mock_submit.call_args.kwargs["job_key"] == JobKey.refresh_data_catalog
    assert mock_submit.call_args.kwargs["kwargs"] == {
        "table_group_id": str(table_group.id),
        "monitor_suite_id": None,
        "run_profiling": False,
    }


@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.JobExecution.submit")
@patch(f"{MODULE}.run_monitor_generation")
@patch(f"{MODULE}.run_data_chars_refresh")
@patch(f"{MODULE}.set_target_db_params")
@patch(f"{MODULE}.Connection.get")
@patch(f"{MODULE}.TableGroup.get")
def test_catalog_refresh_runs_its_steps_in_order(
    mock_tg, _conn, _target, mock_refresh, mock_gen, mock_submit, _session,
):
    mock_tg.return_value = _table_group()
    steps = MagicMock()
    steps.attach_mock(mock_refresh, "refresh")
    steps.attach_mock(mock_gen, "generate")
    steps.attach_mock(mock_submit, "submit")
    table_group_id, monitor_suite_id = str(uuid4()), str(uuid4())

    run_catalog_refresh(table_group_id, monitor_suite_id=monitor_suite_id, run_profiling=True)

    assert [name for name, *_ in steps.mock_calls] == ["refresh", "generate", "submit"]
    # The profiling run counts the rows itself, so this refresh reads no table's data.
    assert mock_refresh.call_args.kwargs == {"count_rows": False}
    assert mock_gen.call_args == call(monitor_suite_id, INITIAL_MONITOR_TYPES)
    assert mock_submit.call_args.kwargs["job_key"] == JobKey.run_profile
    assert mock_submit.call_args.kwargs["kwargs"] == {"table_group_id": table_group_id}


@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.JobExecution.submit")
@patch(f"{MODULE}.run_monitor_generation")
@patch(f"{MODULE}.run_data_chars_refresh", side_effect=RuntimeError("Error refreshing row counts"))
@patch(f"{MODULE}.set_target_db_params")
@patch(f"{MODULE}.Connection.get")
@patch(f"{MODULE}.TableGroup.get")
def test_a_failed_refresh_still_runs_the_other_steps_and_fails_the_job(
    mock_tg, _conn, _target, _refresh, mock_gen, mock_submit, mock_session,
):
    mock_tg.return_value = _table_group()

    with pytest.raises(RuntimeError, match="row counts"):
        run_catalog_refresh(str(uuid4()), monitor_suite_id=str(uuid4()), run_profiling=True)

    mock_gen.assert_called_once()
    mock_submit.assert_called_once()
    # The job fails after this point, so the profiling submission must already be committed.
    mock_session.return_value.commit.assert_called_once()


@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.JobExecution.submit")
@patch(f"{MODULE}.run_monitor_generation", side_effect=RuntimeError("generation failed"))
@patch(f"{MODULE}.run_data_chars_refresh")
@patch(f"{MODULE}.set_target_db_params")
@patch(f"{MODULE}.Connection.get")
@patch(f"{MODULE}.TableGroup.get")
def test_a_failed_monitor_generation_still_submits_profiling_and_fails_the_job(
    mock_tg, _conn, _target, _refresh, _gen, mock_submit, mock_session,
):
    mock_tg.return_value = _table_group()

    with pytest.raises(RuntimeError, match="generation failed"):
        run_catalog_refresh(str(uuid4()), monitor_suite_id=str(uuid4()), run_profiling=True)

    mock_session.return_value.rollback.assert_called_once()
    mock_submit.assert_called_once()
    mock_session.return_value.commit.assert_called_once()


@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.JobExecution.submit")
@patch(f"{MODULE}.run_monitor_generation", side_effect=RuntimeError("generation failed"))
@patch(f"{MODULE}.run_data_chars_refresh", side_effect=RuntimeError("Error refreshing row counts"))
@patch(f"{MODULE}.set_target_db_params")
@patch(f"{MODULE}.Connection.get")
@patch(f"{MODULE}.TableGroup.get")
def test_the_refresh_error_is_the_one_the_job_reports(mock_tg, _conn, _target, _refresh, _gen, _submit, _session):
    mock_tg.return_value = _table_group()

    with pytest.raises(RuntimeError, match="row counts"):
        run_catalog_refresh(str(uuid4()), monitor_suite_id=str(uuid4()))


@patch(f"{MODULE}.JobExecution.submit")
@patch(f"{MODULE}.run_monitor_generation")
@patch(f"{MODULE}.run_data_chars_refresh")
@patch(f"{MODULE}.set_target_db_params")
@patch(f"{MODULE}.Connection.get")
@patch(f"{MODULE}.TableGroup.get")
def test_catalog_refresh_alone_has_no_follow_ups(mock_tg, _conn, _target, mock_refresh, mock_gen, mock_submit):
    mock_tg.return_value = _table_group()

    run_catalog_refresh(str(uuid4()))

    assert mock_refresh.call_args.kwargs == {"count_rows": True}
    mock_gen.assert_not_called()
    mock_submit.assert_not_called()


@patch(f"{MODULE}.JobExecution.submit")
@patch(f"{MODULE}.run_monitor_generation")
@patch(f"{MODULE}.run_data_chars_refresh")
@patch(f"{MODULE}.Connection.get")
@patch(f"{MODULE}.TableGroup.get", return_value=None)
def test_a_refresh_whose_table_group_was_deleted_completes_without_doing_anything(
    _tg, mock_conn, mock_refresh, mock_gen, mock_submit, caplog
):
    table_group_id = str(uuid4())

    with caplog.at_level("INFO", logger="testgen"):
        run_catalog_refresh(table_group_id, monitor_suite_id=str(uuid4()), run_profiling=True)

    mock_conn.assert_not_called()
    mock_refresh.assert_not_called()
    mock_gen.assert_not_called()
    mock_submit.assert_not_called()
    assert caplog.messages == [f"Skipping data catalog refresh: table group {table_group_id} no longer exists"]
