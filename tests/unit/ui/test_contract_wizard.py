# tests/unit/ui/test_contract_wizard.py
"""Unit tests for create_contract_wizard(). pytest -m unit"""
from __future__ import annotations
from unittest.mock import MagicMock, patch, call
import pytest

pytestmark = pytest.mark.unit

PROJECT = "P1"
TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
CONTRACT_ID = "ccc-111"
SUITE_ID = "sss-222"


@pytest.fixture(autouse=True)
def patch_streamlit(monkeypatch):
    """Prevent Streamlit runtime errors in unit test context."""
    import streamlit as st
    monkeypatch.setattr(st, "session_state", {}, raising=False)


class Test_WizardStateInit:
    def test_wizard_key_initialized_on_first_call(self, monkeypatch):
        """wizard_state key is set in session_state when wizard runs."""
        import streamlit as st
        from testgen.ui.views.dialogs.data_contract_dialogs import _init_wizard_state
        monkeypatch.setattr(st, "session_state", {})
        _init_wizard_state(project_code=PROJECT)
        assert "create_contract_wizard" in st.session_state

    def test_wizard_starts_at_step_1_without_tg(self, monkeypatch):
        import streamlit as st
        from testgen.ui.views.dialogs.data_contract_dialogs import _init_wizard_state
        monkeypatch.setattr(st, "session_state", {})
        state = _init_wizard_state(project_code=PROJECT)
        assert state["step"] == 1
        assert state["table_group_id"] is None

    def test_wizard_starts_at_step_2_with_tg(self, monkeypatch):
        import streamlit as st
        from testgen.ui.views.dialogs.data_contract_dialogs import _init_wizard_state
        monkeypatch.setattr(st, "session_state", {})
        state = _init_wizard_state(project_code=PROJECT, table_group_id=TG_ID)
        assert state["step"] == 2
        assert state["table_group_id"] == TG_ID


class Test_ContractNameValidation:
    def test_empty_name_is_invalid(self):
        from testgen.ui.views.dialogs.data_contract_dialogs import _validate_contract_name
        ok, msg = _validate_contract_name("", PROJECT)
        assert not ok
        assert msg  # some error message

    def test_taken_name_is_invalid(self):
        from testgen.ui.views.dialogs.data_contract_dialogs import _validate_contract_name
        with patch("testgen.ui.views.dialogs.data_contract_dialogs.is_contract_name_taken", return_value=True):
            ok, msg = _validate_contract_name("existing", PROJECT)
        assert not ok
        assert "already" in msg.lower() or "taken" in msg.lower() or "exists" in msg.lower()

    def test_unique_name_is_valid(self):
        from testgen.ui.views.dialogs.data_contract_dialogs import _validate_contract_name
        with patch("testgen.ui.views.dialogs.data_contract_dialogs.is_contract_name_taken", return_value=False):
            ok, msg = _validate_contract_name("new_contract", PROJECT)
        assert ok
        assert msg == ""
