"""Tests for the Add Table Group wizard's save branch in ``ui/views/table_groups.py``.

Drives ``_build_wizard_data`` across the two script runs the real wizard takes: the first
returns the event handlers, the second executes the save branch the handler armed via
``temp_value``.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from testgen.common.table_filter_validation import InvalidTableFilters

pytestmark = pytest.mark.unit


class _AnyTable:
    """Stands in for the table group's tables, holding every name; membership is tested in the service tests."""

    def __contains__(self, _name: object) -> bool:
        return True


@pytest.fixture(autouse=True)
def _table_group_holds_every_table():
    with (
        patch("testgen.common.database.table_group_service._table_names", return_value=_AnyTable()),
        patch("testgen.common.database.table_group_service._catalog_table_names", return_value=set()),
    ):
        yield

MODULE = "testgen.ui.views.table_groups"

PROJECT_CODE = "demo"
CONNECTIONS = [{"connection_id": 1}]


def _payload(table_filters: list[dict] | None = None, **standard_suite) -> dict:
    return {
        "table_group": {"table_groups_name": "Sales", "table_group_schema": "sales", "table_filters": table_filters},
        "table_group_verified": True,
        "run_profiling": False,
        "standard_test_suite": {"schedule": "0 6 * * *", "timezone": "UTC", **standard_suite},
        "monitor_test_suite": {"generate": False},
    }


def _integrity_error(constraint: str) -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception(f'violates unique constraint "{constraint}"'))


def _save(
    payload: dict, *, suite_save_error=None, table_group_save_error=None, filter_error=None,
) -> tuple[dict, dict[str, MagicMock]]:
    """Run the wizard's save flow on ``payload`` and return the wizard data of the second run with
    the patched mocks. The errors are what saving the test suite and the table group, and checking
    the table filters against the database, raise.
    """
    from testgen.common.models import _current_session_wrapper
    from testgen.ui import session as session_module

    # database_session() yields an existing session when one is set, so the
    # @with_database_session decorator becomes a passthrough with no DB.
    session = MagicMock()
    _current_session_wrapper.value = session
    try:
        with (
            patch.object(session_module, "st", MagicMock(session_state={})),
            patch(f"{MODULE}.Connection") as connection_cls,
            patch(
                "testgen.common.database.table_group_service.validate_table_filters", side_effect=filter_error,
            ) as validate_table_filters,
            patch(f"{MODULE}.apply_table_group_flavor_rules"),
            patch(f"{MODULE}.table_group_queries") as mock_queries,
            patch(f"{MODULE}.save_new_table_group", side_effect=table_group_save_error) as save_new_table_group,
            patch(f"{MODULE}.record_table_group_created"),
            patch(f"{MODULE}.TestSuite") as test_suite_cls,
            patch(f"{MODULE}.JobSchedule"),
            patch(f"{MODULE}.record"),
            patch(f"{MODULE}.enable_monitoring"),
            patch(f"{MODULE}.submit_table_group_setup") as submit,
        ):
            mock_queries.get_table_group_preview.return_value = None
            test_suite_cls.return_value.save.side_effect = suite_save_error
            from testgen.ui.views.table_groups import TableGroupsPage

            page = TableGroupsPage.__new__(TableGroupsPage)
            _, handlers, _ = page._build_wizard_data(PROJECT_CODE, CONNECTIONS)
            handlers["on_SaveTableGroupClicked_change"](payload)
            data, _, _ = page._build_wizard_data(PROJECT_CODE, CONNECTIONS)
    finally:
        _current_session_wrapper.value = None

    return data, {
        "session": session,
        "save_new_table_group": save_new_table_group,
        "test_suite_cls": test_suite_cls,
        "submit": submit,
        "connection": connection_cls.get.return_value,
        "validate_table_filters": validate_table_filters,
    }


def test_wizard_reports_a_test_suite_name_another_suite_in_the_project_holds():
    data, mocks = _save(
        _payload(generate=True, name=" Sales Tests "),
        suite_save_error=_integrity_error("test_suites_name_unique"),
    )

    assert data["results"]["success"] is False
    assert data["results"]["message"] == "A test suite named Sales Tests already exists in this project."
    mocks["session"].rollback.assert_called_once()
    mocks["submit"].assert_not_called()


def test_wizard_still_reports_a_table_group_name_another_table_group_holds():
    data, _ = _save(
        _payload(generate=True, name="Sales Tests"),
        table_group_save_error=_integrity_error("table_groups_name_unique"),
    )

    assert data["results"]["message"] == "A Table Group with the same name already exists."


def test_wizard_saves_the_table_group_and_its_test_suite():
    data, mocks = _save(_payload(generate=True, name="Sales Tests"))

    mocks["save_new_table_group"].assert_called_once()
    mocks["test_suite_cls"].return_value.save.assert_called_once()
    assert data["results"]["success"] is True


def test_wizard_saves_table_filters_normalized_and_checked_against_the_connection():
    _, mocks = _save(_payload(table_filters=[
        {"table_name": " orders ", "condition": " region = 'EMEA' "},
        {"table_name": "", "condition": ""},
    ]))

    expected = [{"table_name": "orders", "condition": "region = 'EMEA'"}]
    table_group = mocks["save_new_table_group"].call_args.args[0]
    assert table_group.table_filters == expected
    mocks["validate_table_filters"].assert_called_once_with(mocks["connection"], table_group, expected)
    assert table_group.table_group_schema == "sales"


def test_wizard_saves_no_table_filters_without_checking_the_database():
    _, mocks = _save(_payload(table_filters=[{"table_name": " ", "condition": ""}]))

    assert mocks["save_new_table_group"].call_args.args[0].table_filters is None
    mocks["validate_table_filters"].assert_not_called()


def test_wizard_refuses_a_table_filter_without_a_condition():
    data, mocks = _save(_payload(table_filters=[{"table_name": "orders", "condition": ""}]))

    assert data["results"]["success"] is False
    assert data["results"]["message"] == "Enter a filter condition for table orders."
    mocks["save_new_table_group"].assert_not_called()
    mocks["submit"].assert_not_called()


def test_wizard_refuses_a_table_filter_the_database_rejects():
    data, mocks = _save(
        _payload(table_filters=[{"table_name": "orders", "condition": "regon = 1"}]),
        filter_error=InvalidTableFilters("The filter for table orders is not valid: column regon does not exist"),
    )

    assert data["results"]["success"] is False
    assert data["results"]["message"] == "The filter for table orders is not valid: column regon does not exist"
    mocks["save_new_table_group"].assert_not_called()
