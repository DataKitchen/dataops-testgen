"""Tests for the Data Configuration Setup wizard handler in ``ui/views/connections.py``.

Drives ``setup_data_configuration`` across the two script runs the real wizard takes:
the first returns the event handlers, the second executes the save branch that the
handler armed via ``temp_value``.
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.views.connections"

PROJECT_CODE = "demo"
CONNECTION_ID = "1"


def _payload(monitor_suite: dict) -> dict:
    return {
        "table_group": {"table_groups_name": "Sales"},
        "table_group_verified": True,
        "run_profiling": False,
        "standard_test_suite": {"generate": False},
        "monitor_test_suite": monitor_suite,
    }


def _monitor_suite(**overrides) -> dict:
    return {
        "generate": True,
        "monitor_lookback": 14,
        "schedule": "0 */12 * * *",
        "timezone": "UTC",
        "predict_sensitivity": "medium",
        "predict_min_lookback": 30,
        "predict_exclude_weekends": False,
        "predict_holiday_codes": None,
        **overrides,
    }


def _save_via_wizard(monitor_suite: dict) -> MagicMock:
    """Run the wizard's save flow and return the patched ``enable_monitoring`` mock."""
    from testgen.common.models import _current_session_wrapper
    from testgen.ui import session as session_module

    # database_session() yields an existing session when one is set, so the
    # @with_database_session decorator becomes a passthrough with no DB.
    _current_session_wrapper.value = MagicMock()
    session_state: dict = {}

    try:
        with (
            patch.object(session_module, "st", MagicMock(session_state=session_state)),
            patch(f"{MODULE}.enable_monitoring", return_value=(MagicMock(), 3)) as mock_enable,
            patch(f"{MODULE}.TableGroup"),
            patch(f"{MODULE}.table_group_queries") as mock_queries,
            patch(f"{MODULE}.session"),
        ):
            mock_queries.get_table_group_preview.return_value = (None, None)

            from testgen.ui.views.connections import ConnectionsPage

            page = ConnectionsPage.__new__(ConnectionsPage)

            _, handlers = page.setup_data_configuration(PROJECT_CODE, CONNECTION_ID)
            handlers["on_SaveTableGroupClicked_change"](_payload(monitor_suite))

            page.setup_data_configuration(PROJECT_CODE, CONNECTION_ID)

            return mock_enable
    finally:
        _current_session_wrapper.value = None


@pytest.mark.parametrize(
    ("checkbox_value", "expected"),
    [
        (False, False),
        (True, True),
    ],
)
def test_wizard_forwards_regenerate_freshness_choice(checkbox_value, expected):
    mock_enable = _save_via_wizard(_monitor_suite(monitor_regenerate_freshness=checkbox_value))

    mock_enable.assert_called_once()
    assert mock_enable.call_args.kwargs["suite_attrs"]["monitor_regenerate_freshness"] is expected


def test_wizard_forwards_remaining_monitor_settings():
    mock_enable = _save_via_wizard(
        _monitor_suite(
            monitor_regenerate_freshness=False,
            monitor_lookback=20,
            predict_sensitivity="high",
            predict_min_lookback=45,
            predict_exclude_weekends=True,
            predict_holiday_codes="US",
        )
    )

    suite_attrs = mock_enable.call_args.kwargs["suite_attrs"]
    assert suite_attrs == {
        "monitor_lookback": 20,
        "monitor_regenerate_freshness": False,
        "predict_min_lookback": 45,
        "predict_sensitivity": "high",
        "predict_exclude_weekends": True,
        "predict_holiday_codes": "US",
    }


def test_wizard_defaults_timezone_when_absent():
    mock_enable = _save_via_wizard(_monitor_suite(timezone=None))

    assert mock_enable.call_args.args[2] == "UTC"


def test_wizard_skips_monitoring_when_not_requested():
    mock_enable = _save_via_wizard(_monitor_suite(generate=False))

    mock_enable.assert_not_called()
