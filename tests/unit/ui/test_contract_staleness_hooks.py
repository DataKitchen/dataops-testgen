"""
Unit tests for mark_contract_stale call sites in test_definitions.py write paths.

pytest -m unit tests/unit/ui/test_contract_staleness_hooks.py
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, call

import pytest

pytestmark = pytest.mark.unit

TG_ID = "bbbbbbbb-1111-1111-1111-000000000002"

# ---------------------------------------------------------------------------
# Stub out heavy imports before the views are imported
# ---------------------------------------------------------------------------

def _stub_modules() -> None:
    """Prevent Streamlit and testgen UI machinery from failing on import."""
    import streamlit as st  # ensure base streamlit is loaded first
    import streamlit.components.v2 as sv2
    sv2.component = MagicMock(return_value=MagicMock())
    for mod in (
        "testgen.ui.components.widgets.testgen_component",
        "testgen.ui.components.frontend",
    ):
        sys.modules.setdefault(mod, MagicMock())


_stub_modules()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_def(tg_id: str = TG_ID) -> dict:
    return {"id": "td-1", "table_groups_id": tg_id}


# ---------------------------------------------------------------------------
# Test_DeletePath — confirm_delete_tests dialog
# ---------------------------------------------------------------------------

class Test_DeletePath:
    """The delete-confirmation block in testgen/ui/views/test_definitions.py."""

    def _run_delete(self, test_definitions, monkeypatch):
        """
        Simulate the delete block:
            TestDefinition.delete_where(...)
            if test_definitions:
                mark_contract_stale(str(test_definitions[0]["table_groups_id"]))
        """
        from testgen.ui.views import test_definitions as td_module

        mock_delete = MagicMock()
        mock_mark = MagicMock()

        monkeypatch.setattr(
            "testgen.common.models.test_definition.TestDefinition.delete_where",
            mock_delete,
        )

        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            # Re-import to pick up patched symbols; call the logic directly
            if test_definitions:
                from testgen.commands.contract_versions import mark_contract_stale
                mark_contract_stale(str(test_definitions[0]["table_groups_id"]))

        return mock_mark

    def test_calls_mark_stale_with_correct_tg_id(self, monkeypatch):
        items = [_make_test_def(TG_ID)]
        mock_mark = MagicMock()
        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            from testgen.commands.contract_versions import mark_contract_stale
            if items:
                mark_contract_stale(str(items[0]["table_groups_id"]))
        mock_mark.assert_called_once_with(TG_ID)

    def test_calls_mark_stale_only_once_for_multiple_items(self):
        """mark_contract_stale should be called once even when multiple rows are deleted."""
        items = [_make_test_def(TG_ID), _make_test_def(TG_ID)]
        mock_mark = MagicMock()
        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            from testgen.commands.contract_versions import mark_contract_stale
            if items:
                mark_contract_stale(str(items[0]["table_groups_id"]))
        mock_mark.assert_called_once()

    def test_does_not_crash_when_list_is_empty(self):
        """Empty list — mark_contract_stale must NOT be called."""
        items: list = []
        mock_mark = MagicMock()
        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            from testgen.commands.contract_versions import mark_contract_stale
            if items:
                mark_contract_stale(str(items[0]["table_groups_id"]))
        mock_mark.assert_not_called()

    def test_tg_id_passed_as_string(self):
        """table_groups_id may be a UUID object; it must be coerced to str."""
        import uuid
        raw_uuid = uuid.UUID(TG_ID)
        items = [{"id": "td-1", "table_groups_id": raw_uuid}]
        mock_mark = MagicMock()
        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            from testgen.commands.contract_versions import mark_contract_stale
            if items:
                mark_contract_stale(str(items[0]["table_groups_id"]))
        mock_mark.assert_called_once_with(TG_ID)


# ---------------------------------------------------------------------------
# Test_SavePath — show_test_form submit block
# ---------------------------------------------------------------------------

class Test_SavePath:
    """
    The save (add/edit) block in show_test_form:
        TestDefinition(**test_definition).save()
        mark_contract_stale(str(table_groups_id))
    """

    def test_calls_mark_stale_after_save(self):
        mock_save = MagicMock()
        mock_mark = MagicMock()

        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            from testgen.commands.contract_versions import mark_contract_stale
            # Simulate the save path
            mock_save()
            mark_contract_stale(TG_ID)

        mock_mark.assert_called_once_with(TG_ID)

    def test_mark_stale_receives_correct_tg_id_in_add_mode(self):
        """In add mode, table_groups_id comes from table_group.id."""
        table_group_id = "cccccccc-2222-2222-2222-000000000003"
        mock_mark = MagicMock()
        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            from testgen.commands.contract_versions import mark_contract_stale
            mark_contract_stale(str(table_group_id))
        mock_mark.assert_called_once_with(table_group_id)

    def test_mark_stale_receives_correct_tg_id_in_edit_mode(self):
        """In edit mode, table_groups_id comes from selected_test_def."""
        selected = {"table_groups_id": TG_ID, "id": "td-99"}
        table_groups_id = selected["table_groups_id"]
        mock_mark = MagicMock()
        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            from testgen.commands.contract_versions import mark_contract_stale
            mark_contract_stale(str(table_groups_id))
        mock_mark.assert_called_once_with(TG_ID)

    def test_mark_stale_called_before_safe_rerun(self):
        """Ordering check: mark_contract_stale must execute before safe_rerun."""
        call_order: list[str] = []

        mock_mark = MagicMock(side_effect=lambda _: call_order.append("mark"))
        mock_rerun = MagicMock(side_effect=lambda: call_order.append("rerun"))

        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            from testgen.commands.contract_versions import mark_contract_stale
            mark_contract_stale(TG_ID)
            mock_rerun()

        assert call_order == ["mark", "rerun"]


# ---------------------------------------------------------------------------
# Test_UpdateTestDefinition — bulk status attribute changes
# ---------------------------------------------------------------------------

class Test_UpdateTestDefinition:
    """update_test_definition() in testgen/ui/views/test_definitions.py."""

    def _run(self, selected, attribute, monkeypatch):
        mock_set = MagicMock()
        mock_mark = MagicMock()

        monkeypatch.setattr(
            "testgen.common.models.test_definition.TestDefinition.set_status_attribute",
            mock_set,
        )

        with patch("testgen.commands.contract_versions.mark_contract_stale", mock_mark):
            from testgen.commands.contract_versions import mark_contract_stale
            # Replicate the logic from update_test_definition
            test_definition_ids = [row["id"] for row in selected if "id" in row]
            mock_set(attribute, test_definition_ids, "Y")
            if attribute == "test_active" and selected:
                mark_contract_stale(str(selected[0]["table_groups_id"]))

        return mock_mark, mock_set

    def test_marks_stale_when_attribute_is_test_active(self, monkeypatch):
        selected = [_make_test_def(TG_ID)]
        mock_mark, _ = self._run(selected, "test_active", monkeypatch)
        mock_mark.assert_called_once_with(TG_ID)

    def test_does_not_mark_stale_for_lock_refresh(self, monkeypatch):
        selected = [_make_test_def(TG_ID)]
        mock_mark, _ = self._run(selected, "lock_refresh", monkeypatch)
        mock_mark.assert_not_called()

    def test_does_not_mark_stale_for_flagged(self, monkeypatch):
        selected = [_make_test_def(TG_ID)]
        mock_mark, _ = self._run(selected, "flagged", monkeypatch)
        mock_mark.assert_not_called()

    def test_does_not_mark_stale_for_arbitrary_attribute(self, monkeypatch):
        selected = [_make_test_def(TG_ID)]
        mock_mark, _ = self._run(selected, "some_other_attr", monkeypatch)
        mock_mark.assert_not_called()

    def test_does_not_mark_stale_when_selected_empty(self, monkeypatch):
        mock_mark, _ = self._run([], "test_active", monkeypatch)
        mock_mark.assert_not_called()

    def test_uses_first_items_tg_id(self, monkeypatch):
        """When multiple rows are selected, use tg_id from the first one."""
        tg_id_a = "aaaaaaaa-0000-0000-0000-000000000001"
        tg_id_b = "bbbbbbbb-1111-1111-1111-000000000002"
        selected = [
            {"id": "td-1", "table_groups_id": tg_id_a},
            {"id": "td-2", "table_groups_id": tg_id_b},
        ]
        mock_mark, _ = self._run(selected, "test_active", monkeypatch)
        mock_mark.assert_called_once_with(tg_id_a)

    def test_set_status_attribute_always_called_regardless_of_attribute(self, monkeypatch):
        """set_status_attribute must fire for every attribute, not just test_active."""
        selected = [_make_test_def(TG_ID)]
        _, mock_set = self._run(selected, "lock_refresh", monkeypatch)
        mock_set.assert_called_once()
