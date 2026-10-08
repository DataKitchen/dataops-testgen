"""Tests for ``common/monitor_service.py`` — enable / update / disable orchestration."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.enums import SuiteType

pytestmark = pytest.mark.unit

MODULE = "testgen.common.monitor_service"


def _table_group(**overrides) -> MagicMock:
    tg = MagicMock()
    tg.id = overrides.get("id", uuid4())
    tg.project_code = overrides.get("project_code", "demo")
    tg.table_groups_name = overrides.get("table_groups_name", "Sales")
    tg.connection_id = overrides.get("connection_id", 1)
    tg.monitor_test_suite_id = overrides.get("monitor_test_suite_id", None)
    return tg


# ---------------------------------------------------------------------------
# enable_monitoring
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.get_current_session")
def test_enable_monitoring_rejects_when_already_enabled(mock_session, mock_ts):
    """The check reads the locked row, so a table group enabled by a concurrent request is caught
    even when this request's copy of it still says monitoring is off."""
    mock_session.return_value.scalar.return_value = uuid4()

    from testgen.common.monitor_service import enable_monitoring

    with pytest.raises(ValueError, match="already enabled"):
        enable_monitoring(_table_group(monitor_test_suite_id=None), "0 6 * * *")
    mock_ts.assert_not_called()


@patch(f"{MODULE}.get_current_session")
def test_lock_monitor_link_locks_the_table_group_row(mock_session):
    from sqlalchemy.dialects import postgresql

    from testgen.common.monitor_service import lock_monitor_link

    suite_id = uuid4()
    mock_session.return_value.scalar.return_value = suite_id
    tg = _table_group()

    assert lock_monitor_link(tg) == suite_id
    query = mock_session.return_value.scalar.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert sql.startswith("SELECT table_groups.monitor_test_suite_id")
    assert f"WHERE table_groups.id = '{tg.id}'" in sql
    assert sql.endswith("FOR UPDATE")


@patch(f"{MODULE}.JobSchedule")
def test_create_monitor_schedule_targets_the_monitor_suite(mock_js):
    from testgen.common.monitor_service import create_monitor_schedule

    suite = MagicMock(id=uuid4(), project_code="demo")

    schedule = create_monitor_schedule(suite, "0 6 * * *", "UTC")

    assert schedule is mock_js.return_value
    assert mock_js.call_args.kwargs == {
        "project_code": "demo",
        "key": "run-monitors",
        "kwargs": {"test_suite_id": str(suite.id)},
        "cron_expr": "0 6 * * *",
        "cron_tz": "UTC",
        "active": True,
    }
    schedule.save.assert_called_once()


@patch(f"{MODULE}.run_monitor_generation")
@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.TestSuite")
def test_enable_monitoring_merges_defaults_skipping_none(mock_ts, mock_js, mock_session, mock_gen):
    tg = _table_group()
    suite = mock_ts.return_value
    suite.id = uuid4()
    mock_session.return_value.scalar.side_effect = [None, 4]  # the locked link, then the monitor count

    from testgen.common.monitor_service import enable_monitoring

    returned_suite, count = enable_monitoring(
        tg,
        "0 6 * * *",
        "UTC",
        # monitor_lookback=None must fall back to the default; False must be honored (not None).
        suite_attrs={"monitor_lookback": None, "predict_sensitivity": "high", "predict_exclude_weekends": False},
    )

    kwargs = mock_ts.call_args.kwargs
    assert kwargs["suite_type"] == SuiteType.MONITOR
    assert kwargs["monitor_lookback"] == 14            # None override skipped → default
    assert kwargs["predict_sensitivity"] == "high"     # override applied
    assert kwargs["predict_exclude_weekends"] is False  # False is not None → applied
    assert kwargs["predict_min_lookback"] == 30        # untouched default
    assert returned_suite is suite
    assert count == 4
    mock_gen.assert_called_once_with(suite.id, ["Volume_Trend", "Schema_Drift"], in_session=True)
    tg.save.assert_not_called()
    [link_update] = [
        call.args[0] for call in mock_session.return_value.execute.call_args_list
        if str(call.args[0]).startswith("UPDATE table_groups")
    ]
    sql = str(link_update.compile(dialect=postgresql.dialect()))
    assert sql.startswith("UPDATE table_groups SET monitor_test_suite_id=")
    assert "WHERE table_groups.id =" in sql
    assert link_update.compile().params["monitor_test_suite_id"] == suite.id
    assert tg.monitor_test_suite_id == suite.id
    mock_session.return_value.commit.assert_not_called()


@pytest.mark.parametrize(
    ("provided", "expected"),
    [
        (False, False),
        (True, True),
        (None, True),
    ],
)
@patch(f"{MODULE}.run_monitor_generation")
@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.TestSuite")
def test_enable_monitoring_honors_regenerate_freshness(
    mock_ts, mock_js, mock_session, mock_gen, provided, expected
):
    mock_ts.return_value.id = uuid4()
    mock_session.return_value.scalar.side_effect = [None, 0]

    from testgen.common.monitor_service import enable_monitoring

    enable_monitoring(
        _table_group(),
        "0 6 * * *",
        "UTC",
        suite_attrs={"monitor_regenerate_freshness": provided},
    )

    assert mock_ts.call_args.kwargs["monitor_regenerate_freshness"] is expected


# ---------------------------------------------------------------------------
# update_monitoring
# ---------------------------------------------------------------------------


def test_update_monitoring_whitelists_suite_attrs_and_edits_schedule_in_place():
    suite = SimpleNamespace(save=MagicMock())
    schedule = SimpleNamespace(cron_expr="0 6 * * *", cron_tz="UTC", active=True, save=MagicMock())

    from testgen.common.monitor_service import update_monitoring

    update_monitoring(
        suite,
        schedule,
        suite_attrs={
            "predict_sensitivity": "high",
            "predict_holiday_codes": None,
            "suite_type": SuiteType.REGULAR,
        },
        cron_expr="0 */12 * * *",
        active=False,
    )

    # Whitelisted columns applied (a present None clears); non-whitelisted key ignored.
    assert suite.predict_sensitivity == "high"
    assert suite.predict_holiday_codes is None
    assert not hasattr(suite, "suite_type")
    suite.save.assert_called_once()

    # Schedule edited in place — same object, no recreate.
    assert schedule.cron_expr == "0 */12 * * *"
    assert schedule.cron_tz == "UTC"        # not supplied → unchanged
    assert schedule.active is False
    schedule.save.assert_called_once()


# ---------------------------------------------------------------------------
# disable_monitoring
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.get_current_session")
def test_disable_monitoring_counts_before_cascade(mock_session, mock_ts):
    suite = MagicMock()
    suite.id = uuid4()
    mock_session.return_value.scalar.side_effect = [4, 2, 1]  # monitors, events, runs

    from testgen.common.monitor_service import disable_monitoring

    counts = disable_monitoring(suite)

    assert counts == {"monitors": 4, "events": 2, "runs": 1}
    mock_ts.cascade_delete.assert_called_once_with([suite.id])


# ---------------------------------------------------------------------------
# validate_monitor_settings / canonical_holiday_codes / count_monitors
# ---------------------------------------------------------------------------


def test_validate_monitor_settings_accepts_the_defaults():
    from testgen.common.models.test_suite import MONITOR_SETTING_DEFAULTS
    from testgen.common.monitor_service import validate_monitor_settings

    assert validate_monitor_settings(MONITOR_SETTING_DEFAULTS) == []


@pytest.mark.parametrize(
    ("attrs", "message"),
    [
        ({"monitor_lookback": 0}, "`lookback_runs` must be between 1 and 200."),
        ({"monitor_lookback": 201}, "`lookback_runs` must be between 1 and 200."),
        ({"predict_min_lookback": 19}, "`min_training_lookback` must be between 20 and 1000."),
        ({"predict_min_lookback": 1001}, "`min_training_lookback` must be between 20 and 1000."),
        ({"predict_sensitivity": "extreme"}, "`sensitivity` must be one of low, medium, high."),
    ],
)
def test_validate_monitor_settings_reports_each_rule(attrs, message):
    from testgen.common.monitor_service import validate_monitor_settings

    assert validate_monitor_settings(attrs) == [message]


@pytest.mark.parametrize(
    ("attrs",),
    [({"monitor_lookback": 1},), ({"monitor_lookback": 200},), ({"predict_min_lookback": 20},),
     ({"predict_min_lookback": 1000},)],
)
def test_validate_monitor_settings_accepts_range_bounds(attrs):
    from testgen.common.monitor_service import validate_monitor_settings

    assert validate_monitor_settings(attrs) == []


def test_validate_monitor_settings_lists_unknown_holiday_codes():
    from testgen.common.monitor_service import validate_monitor_settings

    [error] = validate_monitor_settings({"predict_holiday_codes": ["US", "ZZ", "QQ"]})

    assert error.startswith("`holiday_codes` has unknown codes: ZZ, QQ.")


def test_validate_monitor_settings_reports_every_failure():
    from testgen.common.monitor_service import validate_monitor_settings

    errors = validate_monitor_settings({
        "monitor_lookback": 0, "predict_min_lookback": 5, "predict_sensitivity": "x", "predict_holiday_codes": ["ZZ"],
    })

    assert len(errors) == 4


def test_canonical_holiday_codes_normalizes_and_deduplicates():
    from testgen.common.monitor_service import canonical_holiday_codes

    assert canonical_holiday_codes([" us", "US", "", "xnys"]) == ["US", "XNYS"]
    assert canonical_holiday_codes([]) is None


@patch(f"{MODULE}.get_current_session")
def test_count_monitors_counts_the_resolved_version(mock_session):
    from sqlalchemy.dialects import postgresql

    from testgen.common.monitor_service import count_monitors

    mock_session.return_value.scalar.return_value = 3
    suite = MagicMock(id=uuid4())

    assert count_monitors(suite) == 3
    query = mock_session.return_value.scalar.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "test_definitions.test_suite_id =" in sql
    assert "test_definitions.version_id =" in sql


def test_table_group_save_never_writes_the_monitor_link():
    """A general edit loaded before monitoring was enabled must not write back a stale link."""
    from testgen.common.models.table_group import TableGroup

    tg = TableGroup(id=uuid4(), table_groups_name="Sales", table_group_schema="public", monitor_test_suite_id=None)
    with patch("testgen.common.models.table_group.get_current_session") as mock_session:
        tg.save()

    statement = mock_session.return_value.execute.call_args.args[0]
    assert "table_groups_name" in statement.compile().params
    assert "monitor_test_suite_id" not in statement.compile().params


def test_validate_monitor_settings_ignores_blank_holiday_codes():
    from testgen.common.monitor_service import validate_monitor_settings

    assert validate_monitor_settings({"predict_holiday_codes": ["US", "", "  "]}) == []
