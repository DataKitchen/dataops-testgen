"""Tests for the Data Configuration Setup wizard handler in ``ui/views/connections.py``.

Drives ``setup_data_configuration`` across the two script runs the real wizard takes:
the first returns the event handlers, the second executes the save branch that the
handler armed via ``temp_value``.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from testgen.common.audit.actions import AuditAction

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
            mock_queries.get_table_group_preview.return_value = None

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


def test_wizard_records_each_object_it_creates():
    from testgen.common.models import _current_session_wrapper
    from testgen.ui import session as session_module

    _current_session_wrapper.value = MagicMock()
    payload = {
        **_payload(_monitor_suite()),
        "standard_test_suite": {"generate": True, "name": "Sales Tests", "schedule": "0 6 * * *", "timezone": "UTC"},
    }
    monitor_suite = MagicMock()
    try:
        with (
            patch.object(session_module, "st", MagicMock(session_state={})),
            patch(f"{MODULE}.enable_monitoring", return_value=(monitor_suite, 0)),
            patch(f"{MODULE}.TableGroup") as table_group_cls,
            patch(f"{MODULE}.TestSuite") as test_suite_cls,
            patch(f"{MODULE}.JobSchedule") as schedule_cls,
            patch(f"{MODULE}.save_new_table_group") as save_new_table_group,
            patch(f"{MODULE}.submit_table_group_setup"),
            patch(f"{MODULE}.record_table_group_created") as record_table_group,
            patch(f"{MODULE}.record_monitoring_enabled") as record_monitoring,
            patch(f"{MODULE}.record") as record,
            patch(f"{MODULE}.table_group_queries") as mock_queries,
            patch(f"{MODULE}.session"),
        ):
            mock_queries.get_table_group_preview.return_value = None
            from testgen.ui.views.connections import ConnectionsPage

            page = ConnectionsPage.__new__(ConnectionsPage)
            _, handlers = page.setup_data_configuration(PROJECT_CODE, CONNECTION_ID)
            handlers["on_SaveTableGroupClicked_change"](payload)
            page.setup_data_configuration(PROJECT_CODE, CONNECTION_ID)
    finally:
        _current_session_wrapper.value = None

    record_table_group.assert_called_once_with(table_group_cls.return_value, save_new_table_group.return_value)
    assert record.call_args_list == [
        ((AuditAction.TEST_SUITE_CREATED, test_suite_cls.return_value),),
        ((AuditAction.SCHEDULE_CREATED, schedule_cls.return_value),),
    ]
    record_monitoring.assert_called_once_with(monitor_suite)


def test_wizard_reports_a_test_suite_name_another_suite_in_the_project_holds():
    from testgen.common.models import _current_session_wrapper
    from testgen.ui import session as session_module

    session = MagicMock()
    _current_session_wrapper.value = session
    payload = {
        **_payload(_monitor_suite(generate=False)),
        "standard_test_suite": {"generate": True, "name": " Sales Tests ", "schedule": "0 6 * * *", "timezone": "UTC"},
    }
    try:
        with (
            patch.object(session_module, "st", MagicMock(session_state={})),
            patch(f"{MODULE}.TableGroup"),
            patch(f"{MODULE}.TestSuite") as test_suite_cls,
            patch(f"{MODULE}.save_new_table_group"),
            patch(f"{MODULE}.record_table_group_created"),
            patch(f"{MODULE}.record"),
            patch(f"{MODULE}.submit_table_group_setup") as submit,
            patch(f"{MODULE}.table_group_queries") as mock_queries,
            patch(f"{MODULE}.session"),
        ):
            test_suite_cls.return_value.save.side_effect = IntegrityError(
                "INSERT", {}, Exception('violates unique constraint "test_suites_name_unique"')
            )
            mock_queries.get_table_group_preview.return_value = None
            from testgen.ui.views.connections import ConnectionsPage

            page = ConnectionsPage.__new__(ConnectionsPage)
            _, handlers = page.setup_data_configuration(PROJECT_CODE, CONNECTION_ID)
            handlers["on_SaveTableGroupClicked_change"](payload)
            data, _ = page.setup_data_configuration(PROJECT_CODE, CONNECTION_ID)
    finally:
        _current_session_wrapper.value = None

    assert data["results"]["success"] is False
    assert data["results"]["message"] == "A test suite or contract named Sales Tests already exists in this project."
    session.rollback.assert_called_once()
    submit.assert_not_called()
