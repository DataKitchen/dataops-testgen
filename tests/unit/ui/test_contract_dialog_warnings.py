"""
Unit tests for save/regenerate dialog warnings and create_contract_snapshot_suite calls.
pytest -m unit tests/unit/ui/test_contract_dialog_warnings.py
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

pytestmark = pytest.mark.unit

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
NEW_SUITE_ID = "cccccccc-0000-0000-0000-000000000003"


# ---------------------------------------------------------------------------
# Fixture: mock Streamlit so dialogs don't need a running app
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_streamlit(monkeypatch):
    """Patch all st.* calls so dialogs can run without a Streamlit runtime."""
    import streamlit as st

    # Track info messages
    info_calls: list[str] = []
    monkeypatch.setattr(st, "info", lambda msg, **_: info_calls.append(msg))
    monkeypatch.setattr(st, "warning", MagicMock())
    monkeypatch.setattr(st, "error", MagicMock())
    monkeypatch.setattr(st, "success", MagicMock())
    monkeypatch.setattr(st, "caption", MagicMock())
    monkeypatch.setattr(st, "markdown", MagicMock())
    monkeypatch.setattr(st, "divider", MagicMock())
    monkeypatch.setattr(st, "checkbox", MagicMock(return_value=True))
    monkeypatch.setattr(st, "text_input", MagicMock(return_value=""))

    # Buttons: only the save/regen buttons return True
    button_call_count = [0]

    def _button(label="", *, type=None, disabled=False, use_container_width=False, key=None, **_kw):
        button_call_count[0] += 1
        if label in ("Save Version", "Regenerate & Save"):
            return True
        return False

    monkeypatch.setattr(st, "button", _button)
    monkeypatch.setattr(st, "columns", lambda n: [MagicMock(button=_button)] * n)
    monkeypatch.setattr(st, "spinner", MagicMock(__enter__=lambda s, *a: None, __exit__=lambda s, *a: None))

    # session_state
    monkeypatch.setattr(st, "session_state", {})

    return info_calls


@pytest.fixture(autouse=True)
def patch_dialog_deps(monkeypatch):
    """Patch DB helpers and navigation so dialogs don't need a real DB."""
    monkeypatch.setattr(
        "testgen.ui.views.dialogs.data_contract_dialogs.with_database_session",
        lambda f: f,
    )
    monkeypatch.setattr(
        "testgen.ui.views.dialogs.data_contract_dialogs.get_tg_schema",
        lambda: "tg",
    )
    monkeypatch.setattr(
        "testgen.ui.views.dialogs.data_contract_dialogs.safe_rerun",
        MagicMock(),
    )


# ---------------------------------------------------------------------------
# _save_version_dialog
# ---------------------------------------------------------------------------

class Test_SaveVersionDialogWarning:

    def test_info_contains_snapshot_suite_name(self, mock_streamlit):
        """The st.info call must include the [Contract v{N}] suite name."""
        import streamlit as st

        mock_tg = MagicMock()
        mock_tg.table_groups_name = "My Group"

        with patch("testgen.ui.views.dialogs.data_contract_dialogs.TableGroup") as mock_tg_cls, \
             patch("testgen.ui.views.dialogs.data_contract_dialogs.save_contract_version",
                   return_value=2), \
             patch("testgen.ui.views.dialogs.data_contract_dialogs.create_contract_snapshot_suite",
                   return_value=NEW_SUITE_ID), \
             patch("testgen.ui.views.dialogs.data_contract_dialogs._persist_pending_edits"):
            mock_tg_cls.get_minimal.return_value = mock_tg

            # Invoke directly (not as a dialog decorator — call underlying function)
            from testgen.ui.views.dialogs.data_contract_dialogs import _save_version_dialog
            # Bypass the @st.dialog decorator by calling __wrapped__ if available
            fn = getattr(_save_version_dialog, "__wrapped__", _save_version_dialog)
            fn(TG_ID, {}, "yaml-content", 1)

        assert any("[Contract v2] My Group" in msg for msg in mock_streamlit), (
            f"Expected snapshot suite name in info messages, got: {mock_streamlit}"
        )

    def test_save_dialog_calls_create_snapshot_suite(self, mock_streamlit):
        """_save_version_dialog must call create_contract_snapshot_suite after save."""
        mock_tg = MagicMock()
        mock_tg.table_groups_name = "My Group"

        with patch("testgen.ui.views.dialogs.data_contract_dialogs.TableGroup") as mock_tg_cls, \
             patch("testgen.ui.views.dialogs.data_contract_dialogs.save_contract_version",
                   return_value=2) as mock_save, \
             patch("testgen.ui.views.dialogs.data_contract_dialogs.create_contract_snapshot_suite",
                   return_value=NEW_SUITE_ID) as mock_snapshot, \
             patch("testgen.ui.views.dialogs.data_contract_dialogs._persist_pending_edits"):
            mock_tg_cls.get_minimal.return_value = mock_tg

            from testgen.ui.views.dialogs.data_contract_dialogs import _save_version_dialog
            fn = getattr(_save_version_dialog, "__wrapped__", _save_version_dialog)
            fn(TG_ID, {}, "yaml-content", 1)

        mock_snapshot.assert_called_once_with(TG_ID, 2)


# ---------------------------------------------------------------------------
# _regenerate_dialog
# ---------------------------------------------------------------------------

class Test_RegenerateDialogWarning:

    def test_regen_dialog_info_contains_snapshot_suite_name(self, mock_streamlit):
        """The regenerate dialog st.info call must include the [Contract v{N}] suite name."""
        import io as _io
        mock_tg = MagicMock()
        mock_tg.table_groups_name = "Orders"

        with patch("testgen.ui.views.dialogs.data_contract_dialogs.TableGroup") as mock_tg_cls, \
             patch("testgen.ui.views.dialogs.data_contract_dialogs._capture_yaml",
                   side_effect=lambda tg_id, buf: buf.write("yaml-content")), \
             patch("testgen.ui.views.dialogs.data_contract_dialogs.save_contract_version",
                   return_value=3), \
             patch("testgen.ui.views.dialogs.data_contract_dialogs.create_contract_snapshot_suite",
                   return_value=NEW_SUITE_ID):
            mock_tg_cls.get_minimal.return_value = mock_tg

            from testgen.ui.views.dialogs.data_contract_dialogs import _regenerate_dialog
            fn = getattr(_regenerate_dialog, "__wrapped__", _regenerate_dialog)
            fn(TG_ID, 2, 0)

        assert any("[Contract v3] Orders" in msg for msg in mock_streamlit), (
            f"Expected snapshot suite name in info messages, got: {mock_streamlit}"
        )

    def test_regen_dialog_calls_create_snapshot_suite(self, mock_streamlit):
        """_regenerate_dialog must call create_contract_snapshot_suite after save."""
        mock_tg = MagicMock()
        mock_tg.table_groups_name = "Orders"

        with patch("testgen.ui.views.dialogs.data_contract_dialogs.TableGroup") as mock_tg_cls, \
             patch("testgen.ui.views.dialogs.data_contract_dialogs._capture_yaml",
                   side_effect=lambda tg_id, buf: buf.write("yaml-content")), \
             patch("testgen.ui.views.dialogs.data_contract_dialogs.save_contract_version",
                   return_value=3), \
             patch("testgen.ui.views.dialogs.data_contract_dialogs.create_contract_snapshot_suite",
                   return_value=NEW_SUITE_ID) as mock_snapshot:
            mock_tg_cls.get_minimal.return_value = mock_tg

            from testgen.ui.views.dialogs.data_contract_dialogs import _regenerate_dialog
            fn = getattr(_regenerate_dialog, "__wrapped__", _regenerate_dialog)
            fn(TG_ID, 2, 0)

        mock_snapshot.assert_called_once_with(TG_ID, 3)
