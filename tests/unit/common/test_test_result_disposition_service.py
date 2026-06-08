from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import Disposition
from testgen.common.test_result_disposition_service import (
    DispositionUpdate,
    coerce_ui_disposition,
    coupled_test_definition_state,
    set_test_results_disposition,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.common.test_result_disposition_service"


class Test_coupled_test_definition_state:
    def test_muted_deactivates_and_locks(self):
        # (test_active, lock_refresh)
        assert coupled_test_definition_state(Disposition.INACTIVE) == (False, True)

    @pytest.mark.parametrize("disposition", [Disposition.CONFIRMED, Disposition.DISMISSED, None])
    def test_other_values_reactivate_and_unlock(self, disposition):
        assert coupled_test_definition_state(disposition) == (True, False)


class Test_coerce_ui_disposition:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("Confirmed", Disposition.CONFIRMED),
            ("Dismissed", Disposition.DISMISSED),
            ("Inactive", Disposition.INACTIVE),
            ("No Decision", None),
            (None, None),
            ("", None),
        ],
    )
    def test_maps_ui_string_to_stored_value(self, value, expected):
        assert coerce_ui_disposition(value) is expected


class Test_set_test_results_disposition:
    def test_empty_ids_is_noop(self):
        with patch(f"{MODULE}.get_current_session") as get_session:
            result = set_test_results_disposition([], Disposition.CONFIRMED)
        assert result == DispositionUpdate(matched=0, passed_skipped=0)
        get_session.assert_not_called()

    def test_returns_matched_and_passed_counts(self):
        session = MagicMock()
        # First call: COUNT of passed rows -> 2. Then the TR update returns rowcount 3.
        session.scalar.return_value = 2
        tr_update_result = MagicMock(rowcount=3)
        session.execute.return_value = tr_update_result
        with patch(f"{MODULE}.get_current_session", return_value=session):
            result = set_test_results_disposition([uuid4(), uuid4()], Disposition.DISMISSED)
        assert result == DispositionUpdate(matched=3, passed_skipped=2)
        # One TR update + one TD update.
        assert session.execute.call_count == 2

    def test_muted_couples_td_to_inactive(self):
        session = MagicMock()
        session.scalar.return_value = 0
        session.execute.return_value = MagicMock(rowcount=1)
        with patch(f"{MODULE}.get_current_session", return_value=session):
            set_test_results_disposition([uuid4()], Disposition.INACTIVE)
        td_stmt = session.execute.call_args_list[1].args[0]
        params = td_stmt.compile().params
        # YNString stores 'N'/'Y'; bound values are the Python bools before type processing.
        assert params["test_active"] is False
        assert params["lock_refresh"] is True

    def test_clear_passes_null_disposition(self):
        session = MagicMock()
        session.scalar.return_value = 0
        session.execute.return_value = MagicMock(rowcount=1)
        with patch(f"{MODULE}.get_current_session", return_value=session):
            set_test_results_disposition([uuid4()], None)
        tr_stmt = session.execute.call_args_list[0].args[0]
        assert tr_stmt.compile().params["disposition"] is None
