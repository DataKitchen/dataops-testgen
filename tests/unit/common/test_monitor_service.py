"""Tests for ``common/monitor_service.py`` — enable / update / disable orchestration."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

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


def test_enable_monitoring_rejects_when_already_enabled():
    from testgen.common.monitor_service import enable_monitoring

    with pytest.raises(ValueError, match="already enabled"):
        enable_monitoring(_table_group(monitor_test_suite_id=uuid4()), "0 6 * * *")


@patch(f"{MODULE}.run_monitor_generation")
@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.TestSuite")
def test_enable_monitoring_merges_defaults_skipping_none(mock_ts, mock_js, mock_session, mock_gen):
    tg = _table_group()
    suite = mock_ts.return_value
    suite.id = uuid4()
    mock_session.return_value.scalar.return_value = 4

    from testgen.common.monitor_service import enable_monitoring

    returned_suite, count = enable_monitoring(
        tg,
        "0 6 * * *",
        "UTC",
        # monitor_lookback=None must fall back to the default; False must be honored (not None).
        suite_attrs={"monitor_lookback": None, "predict_sensitivity": "high", "predict_exclude_weekends": False},
    )

    kwargs = mock_ts.call_args.kwargs
    assert kwargs["is_monitor"] is True
    assert kwargs["monitor_lookback"] == 14            # None override skipped → default
    assert kwargs["predict_sensitivity"] == "high"     # override applied
    assert kwargs["predict_exclude_weekends"] is False  # False is not None → applied
    assert kwargs["predict_min_lookback"] == 30        # untouched default
    assert returned_suite is suite
    assert count == 4
    mock_gen.assert_called_once_with(suite.id, ["Volume_Trend", "Schema_Drift"])
    tg.save.assert_called()
    assert tg.monitor_test_suite_id == suite.id


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
        suite_attrs={"predict_sensitivity": "high", "predict_holiday_codes": None, "is_monitor": False},
        cron_expr="0 */12 * * *",
        active=False,
    )

    # Whitelisted columns applied (a present None clears); non-whitelisted key ignored.
    assert suite.predict_sensitivity == "high"
    assert suite.predict_holiday_codes is None
    assert not hasattr(suite, "is_monitor")
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
