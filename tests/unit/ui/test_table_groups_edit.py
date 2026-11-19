"""Tests for the Edit Table Group dialog's save branch in ``ui/views/table_groups.py``.

Drives ``_build_edit_data`` across the two script runs the real dialog takes: the first returns the
event handlers, the second executes the save branch the handler armed via ``temp_value``.
"""

from unittest.mock import MagicMock, patch

import pytest

from testgen.common.audit.actions import AuditAction
from testgen.common.table_filter_validation import InvalidTableFilters

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.views.table_groups"


def _save(table_filters: list[dict] | None, *, filter_error=None) -> tuple[dict, dict[str, MagicMock]]:
    """Save the table group with ``table_filters`` from the dialog and return the dialog data of the
    second run with the patched mocks. ``filter_error`` is what checking the filters against the
    database raises.
    """
    from testgen.common.models import _current_session_wrapper
    from testgen.ui import session as session_module

    table_group = MagicMock(id="tg-1", connection_id=1, table_group_schema="sales", table_filters=None)
    _current_session_wrapper.value = MagicMock()
    try:
        with (
            patch.object(session_module, "st", MagicMock(session_state={"tg_wizard_table_group_id": "tg-1"})),
            patch(f"{MODULE}.st", MagicMock(session_state={"tg_wizard_table_group_id": "tg-1"})),
            patch(f"{MODULE}.session"),
            patch(f"{MODULE}.get_table_group", return_value=table_group),
            patch(f"{MODULE}.catalog_source"),
            patch(f"{MODULE}.Connection") as connection_cls,
            patch(f"{MODULE}.apply_table_group_flavor_rules"),
            patch(f"{MODULE}.table_group_queries") as mock_queries,
            patch(f"{MODULE}.sampled_profile_gaps"),
            patch(f"{MODULE}.DataTable") as data_table_cls,
            patch(f"{MODULE}.record") as record,
            patch(f"{MODULE}.submit_table_group_setup"),
            patch(f"{MODULE}.safe_rerun"),
            patch(
                "testgen.common.database.table_group_service.validate_table_filters", side_effect=filter_error,
            ) as validate_table_filters,
        ):
            mock_queries.get_table_group_preview.return_value = {"success": True}
            data_table_cls.select_table_names.return_value = ["customers", "orders"]
            from testgen.ui.views.table_groups import TableGroupsPage

            page = TableGroupsPage.__new__(TableGroupsPage)
            _, handlers = page._build_edit_data("demo", [{"connection_id": 1}])
            handlers["on_SaveEditTableGroupClicked_change"](
                {"table_group": {"table_group_schema": "sales", "table_filters": table_filters}},
            )
            data, _ = page._build_edit_data("demo", [{"connection_id": 1}])
    finally:
        _current_session_wrapper.value = None

    return data, {
        "table_group": table_group,
        "connection": connection_cls.get.return_value,
        "record": record,
        "validate_table_filters": validate_table_filters,
    }


def test_edit_saves_table_filters_normalized_and_checked_against_the_connection():
    data, mocks = _save([{"table_name": "orders ", "condition": " region = 'EMEA'"}])

    expected = [{"table_name": "orders", "condition": "region = 'EMEA'"}]
    table_group = mocks["table_group"]
    assert data["result"] is None
    assert table_group.table_filters == expected
    mocks["validate_table_filters"].assert_called_once_with(mocks["connection"], table_group, expected)
    table_group.save.assert_called_once()
    mocks["record"].assert_called_once_with(AuditAction.TABLE_GROUP_UPDATED, table_group)


def test_edit_clears_table_filters_without_checking_the_database():
    _, mocks = _save([])

    assert mocks["table_group"].table_filters is None
    mocks["validate_table_filters"].assert_not_called()
    mocks["table_group"].save.assert_called_once()


def test_edit_refuses_a_table_named_by_two_filters():
    data, mocks = _save([
        {"table_name": "orders", "condition": "region = 'EMEA'"},
        {"table_name": "orders", "condition": "region = 'APAC'"},
    ])

    assert data["result"] == {"success": False, "message": "Table orders has more than one filter."}
    mocks["table_group"].save.assert_not_called()
    mocks["record"].assert_not_called()


def test_edit_refuses_a_table_filter_the_database_rejects():
    data, mocks = _save(
        [{"table_name": "orders", "condition": "regon = 1"}],
        filter_error=InvalidTableFilters("The filter for table orders is not valid: column regon does not exist"),
    )

    assert data["result"] == {
        "success": False,
        "message": "The filter for table orders is not valid: column regon does not exist",
    }
    mocks["table_group"].save.assert_not_called()
    mocks["record"].assert_not_called()


def test_edit_offers_the_catalog_tables_for_table_filters():
    data, _ = _save(None)

    assert data["table_names"] == ["customers", "orders"]
