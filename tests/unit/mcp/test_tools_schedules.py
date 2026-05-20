from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import JobKey
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError


def _make_table_group(project_code="demo", name="orders_tg"):
    tg = MagicMock()
    tg.id = uuid4()
    tg.project_code = project_code
    tg.table_groups_name = name
    return tg


def _make_suite(project_code="demo", name="suite_a", is_monitor=False):
    suite = MagicMock()
    suite.id = uuid4()
    suite.project_code = project_code
    suite.test_suite = name
    suite.is_monitor = is_monitor
    return suite


def _make_sched(*, key=None, active=True, project_code="demo", linked_id=None):
    sched = MagicMock()
    sched.id = uuid4()
    sched.project_code = project_code
    sched.key = key or JobKey.run_profile.value
    sched.cron_expr = "0 3 * * *"
    sched.cron_tz = "UTC"
    sched.active = active
    if sched.key == JobKey.run_profile.value:
        sched.kwargs = {"table_group_id": linked_id or str(uuid4())}
    else:
        sched.kwargs = {"test_suite_id": linked_id or str(uuid4())}
    sched.get_sample_triggering_timestamps.return_value = [datetime(2026, 5, 19, 3, 0)]
    return sched


# ---------------------------------------------------------------------------
# create_profiling_schedule
# ---------------------------------------------------------------------------


@patch("testgen.mcp.tools.schedules.JobSchedule")
@patch("testgen.mcp.tools.schedules.resolve_table_group")
def test_create_profiling_schedule_happy_path(mock_resolve_tg, mock_sched_cls, db_session_mock):
    tg = _make_table_group()
    mock_resolve_tg.return_value = tg
    saved = _make_sched(linked_id=str(tg.id))
    mock_sched_cls.return_value = saved

    from testgen.mcp.tools.schedules import create_profiling_schedule

    result = create_profiling_schedule(
        table_group_id=str(tg.id),
        cron_expression="0 3 * * *",
        cron_tz="UTC",
    )

    assert "Profiling schedule created" in result
    assert "orders_tg" in result
    assert "`0 3 * * *`" in result
    saved.save.assert_called_once()


@patch("testgen.mcp.tools.schedules.resolve_table_group")
def test_create_profiling_schedule_invalid_cron(mock_resolve_tg, db_session_mock):
    mock_resolve_tg.return_value = _make_table_group()

    from testgen.mcp.tools.schedules import create_profiling_schedule

    with pytest.raises(MCPUserError) as exc:
        create_profiling_schedule(
            table_group_id=str(uuid4()),
            cron_expression="not a cron",
            cron_tz="UTC",
        )
    assert "Invalid cron" in str(exc.value)


@patch("testgen.mcp.tools.schedules.resolve_table_group")
def test_create_profiling_schedule_invalid_timezone(mock_resolve_tg, db_session_mock):
    mock_resolve_tg.return_value = _make_table_group()

    from testgen.mcp.tools.schedules import create_profiling_schedule

    with pytest.raises(MCPUserError) as exc:
        create_profiling_schedule(
            table_group_id=str(uuid4()),
            cron_expression="0 3 * * *",
            cron_tz="Not/A_Real_Timezone",
        )
    assert "Invalid cron" in str(exc.value)


@patch("testgen.mcp.tools.schedules.resolve_table_group")
def test_create_profiling_schedule_empty_cron_rejected(mock_resolve_tg, db_session_mock):
    mock_resolve_tg.return_value = _make_table_group()

    from testgen.mcp.tools.schedules import create_profiling_schedule

    with pytest.raises(MCPUserError) as exc:
        create_profiling_schedule(table_group_id=str(uuid4()), cron_expression="")
    assert "cron_expression" in str(exc.value)


@patch("testgen.mcp.tools.schedules.resolve_table_group")
def test_create_profiling_schedule_empty_tz_rejected(mock_resolve_tg, db_session_mock):
    mock_resolve_tg.return_value = _make_table_group()

    from testgen.mcp.tools.schedules import create_profiling_schedule

    with pytest.raises(MCPUserError) as exc:
        create_profiling_schedule(
            table_group_id=str(uuid4()), cron_expression="0 3 * * *", cron_tz=""
        )
    assert "cron_tz" in str(exc.value)


# ---------------------------------------------------------------------------
# create_test_run_schedule
# ---------------------------------------------------------------------------


@patch("testgen.mcp.tools.schedules.JobSchedule")
@patch("testgen.mcp.tools.schedules.resolve_test_suite")
def test_create_test_run_schedule_happy_path(mock_resolve_suite, mock_sched_cls, db_session_mock):
    suite = _make_suite()
    mock_resolve_suite.return_value = suite
    saved = _make_sched(key=JobKey.run_tests.value, linked_id=str(suite.id))
    mock_sched_cls.return_value = saved

    from testgen.mcp.tools.schedules import create_test_run_schedule

    result = create_test_run_schedule(
        test_suite_id=str(suite.id),
        cron_expression="0 6 * * 1",
        cron_tz="UTC",
    )

    assert "Test run schedule created" in result
    assert "suite_a" in result
    saved.save.assert_called_once()


@patch("testgen.mcp.tools.schedules.resolve_test_suite")
def test_create_test_run_schedule_monitor_suite_rejected(mock_resolve_suite, db_session_mock):
    mock_resolve_suite.side_effect = MCPResourceNotAccessible("Test suite", "abc")

    from testgen.mcp.tools.schedules import create_test_run_schedule

    with pytest.raises(MCPResourceNotAccessible):
        create_test_run_schedule(
            test_suite_id=str(uuid4()),
            cron_expression="0 6 * * 1",
        )


# ---------------------------------------------------------------------------
# list_schedules
# ---------------------------------------------------------------------------


@patch("testgen.mcp.tools.schedules._resolve_linked_names")
@patch("testgen.mcp.tools.schedules.JobSchedule")
def test_list_schedules_basic(mock_sched_cls, mock_linked, db_session_mock):
    sched_a = _make_sched(key=JobKey.run_profile.value)
    sched_b = _make_sched(key=JobKey.run_tests.value)
    mock_sched_cls.list_for_project.return_value = ([sched_a, sched_b], 2)
    mock_linked.return_value = {
        ("tg", sched_a.kwargs["table_group_id"]): "orders_tg",
        ("suite", sched_b.kwargs["test_suite_id"]): "suite_a",
    }

    from testgen.mcp.tools.schedules import list_schedules

    result = list_schedules(project_code="demo")

    assert "Schedules" in result
    assert "Profiling Run" in result
    assert "Test Run" in result
    assert "orders_tg" in result
    assert "suite_a" in result


@patch("testgen.mcp.tools.schedules.JobSchedule")
def test_list_schedules_empty(mock_sched_cls, db_session_mock):
    mock_sched_cls.list_for_project.return_value = ([], 0)

    from testgen.mcp.tools.schedules import list_schedules

    result = list_schedules(project_code="demo")
    assert "No schedules" in result


@patch("testgen.mcp.tools.schedules._resolve_linked_names")
@patch("testgen.mcp.tools.schedules.JobSchedule")
def test_list_schedules_type_filter_maps_to_job_key(mock_sched_cls, mock_linked, db_session_mock):
    sched = _make_sched(key=JobKey.run_profile.value)
    mock_sched_cls.list_for_project.return_value = ([sched], 1)
    mock_linked.return_value = {}

    from testgen.mcp.tools.schedules import list_schedules

    list_schedules(project_code="demo", schedule_type="profiling_run")

    call_kwargs = mock_sched_cls.list_for_project.call_args
    assert call_kwargs.kwargs["key_filter"] == [JobKey.run_profile.value]


def test_list_schedules_invalid_schedule_type(db_session_mock):
    from testgen.mcp.tools.schedules import list_schedules

    with pytest.raises(MCPUserError) as exc:
        list_schedules(project_code="demo", schedule_type="not-a-type")
    assert "Invalid schedule_type" in str(exc.value)


def test_list_schedules_project_not_accessible(db_session_mock):
    from testgen.mcp.tools.schedules import list_schedules

    with pytest.raises(MCPResourceNotAccessible):
        list_schedules(project_code="other_project")


# ---------------------------------------------------------------------------
# get_schedule
# ---------------------------------------------------------------------------


@patch("testgen.mcp.tools.schedules.get_current_session")
@patch("testgen.mcp.tools.schedules._resolve_linked_names")
@patch("testgen.mcp.tools.schedules.resolve_schedule")
def test_get_schedule_no_executions(mock_resolve, mock_linked, mock_session, db_session_mock):
    sched = _make_sched(key=JobKey.run_profile.value)
    mock_resolve.return_value = sched
    mock_linked.return_value = {("tg", sched.kwargs["table_group_id"]): "orders_tg"}
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    mock_session.return_value = session

    from testgen.mcp.tools.schedules import get_schedule

    result = get_schedule(schedule_id=str(sched.id))
    assert "orders_tg" in result
    assert "No runs yet" in result


@patch("testgen.mcp.tools.schedules.get_current_session")
@patch("testgen.mcp.tools.schedules._resolve_linked_names")
@patch("testgen.mcp.tools.schedules.resolve_schedule")
def test_get_schedule_with_executions(mock_resolve, mock_linked, mock_session, db_session_mock):
    sched = _make_sched(key=JobKey.run_profile.value)
    mock_resolve.return_value = sched
    mock_linked.return_value = {("tg", sched.kwargs["table_group_id"]): "orders_tg"}

    je = MagicMock()
    je.id = uuid4()
    je.status = "Completed"
    je.created_at = datetime(2026, 5, 18, 3, 0)
    je.started_at = datetime(2026, 5, 18, 3, 0)
    je.completed_at = datetime(2026, 5, 18, 3, 12)
    session = MagicMock()
    session.scalars.return_value.all.return_value = [je]
    mock_session.return_value = session

    from testgen.mcp.tools.schedules import get_schedule

    result = get_schedule(schedule_id=str(sched.id))
    assert "Recent runs" in result
    assert str(je.id) in result


# ---------------------------------------------------------------------------
# update_schedule
# ---------------------------------------------------------------------------


@patch("testgen.mcp.tools.schedules.resolve_schedule")
def test_update_schedule_happy_path_diff(mock_resolve, db_session_mock):
    sched = _make_sched(key=JobKey.run_profile.value, active=True)
    mock_resolve.return_value = sched

    from testgen.mcp.tools.schedules import update_schedule

    result = update_schedule(schedule_id=str(sched.id), active=False)

    assert "Schedule updated" in result
    assert "Active" in result and "Paused" in result
    sched.save.assert_called_once()


def test_update_schedule_empty_payload_rejected(db_session_mock):
    from testgen.mcp.tools.schedules import update_schedule

    with pytest.raises(MCPUserError) as exc:
        update_schedule(schedule_id=str(uuid4()))
    assert "No fields supplied" in str(exc.value)


@patch("testgen.mcp.tools.schedules.resolve_schedule")
def test_update_schedule_invalid_cron(mock_resolve, db_session_mock):
    sched = _make_sched(key=JobKey.run_profile.value)
    mock_resolve.return_value = sched

    from testgen.mcp.tools.schedules import update_schedule

    with pytest.raises(MCPUserError) as exc:
        update_schedule(schedule_id=str(sched.id), cron_expression="garbage")
    assert "Invalid cron" in str(exc.value)
    sched.save.assert_not_called()


@patch("testgen.mcp.tools.schedules.resolve_schedule")
def test_update_schedule_monitor_schedule_not_accessible(mock_resolve, db_session_mock):
    """resolve_schedule filters out monitor schedules — caller sees the unified not-accessible error."""
    mock_resolve.side_effect = MCPResourceNotAccessible("Schedule", "abc")

    from testgen.mcp.tools.schedules import update_schedule

    with pytest.raises(MCPResourceNotAccessible):
        update_schedule(schedule_id=str(uuid4()), active=False)


# ---------------------------------------------------------------------------
# delete_schedule
# ---------------------------------------------------------------------------


@patch("testgen.mcp.tools.schedules.JobSchedule")
@patch("testgen.mcp.tools.schedules.resolve_schedule")
def test_delete_schedule_happy_path(mock_resolve, mock_sched_cls, db_session_mock):
    sched = _make_sched(key=JobKey.run_profile.value)
    mock_resolve.return_value = sched

    from testgen.mcp.tools.schedules import delete_schedule

    result = delete_schedule(schedule_id=str(sched.id))
    assert "Schedule deleted" in result
    mock_sched_cls.delete.assert_called_once_with(sched.id)


@patch("testgen.mcp.tools.schedules.JobSchedule")
@patch("testgen.mcp.tools.schedules.resolve_schedule")
def test_delete_schedule_monitor_schedule_not_accessible(mock_resolve, mock_sched_cls, db_session_mock):
    """resolve_schedule filters out monitor schedules — caller sees the unified not-accessible error."""
    mock_resolve.side_effect = MCPResourceNotAccessible("Schedule", "abc")

    from testgen.mcp.tools.schedules import delete_schedule

    with pytest.raises(MCPResourceNotAccessible):
        delete_schedule(schedule_id=str(uuid4()))
    mock_sched_cls.delete.assert_not_called()
