"""
Unit tests for StaleDiff.summary_parts(), StaleDiff.is_empty,
and _render_staleness_banner().

pytest -m unit tests/unit/ui/test_contract_staleness_ui.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Mock Streamlit machinery before importing app code
# ---------------------------------------------------------------------------

def _mock_streamlit() -> None:
    import streamlit.components.v2 as _sv2
    _sv2.component = MagicMock(return_value=MagicMock())
    sys.modules.setdefault(
        "testgen.ui.components.widgets.testgen_component", MagicMock()
    )

_mock_streamlit()

from testgen.commands.contract_staleness import StaleDiff  # noqa: E402
from testgen.ui.views.data_contract import _render_staleness_banner  # noqa: E402


# ---------------------------------------------------------------------------
# Test_StaleDiffSummaryParts
# ---------------------------------------------------------------------------

class Test_StaleDiffSummaryParts:
    def test_empty_diff_returns_empty_list(self):
        assert StaleDiff().summary_parts() == []

    def test_single_added_column(self):
        diff = StaleDiff(schema_changes=[{"change": "added", "table": "t", "column": "c", "detail": ""}])
        assert diff.summary_parts() == ["1 new column detected"]

    def test_plural_added_columns(self):
        diff = StaleDiff(schema_changes=[
            {"change": "added", "table": "t", "column": "c1", "detail": ""},
            {"change": "added", "table": "t", "column": "c2", "detail": ""},
        ])
        assert diff.summary_parts() == ["2 new columns detected"]

    def test_removed_column(self):
        diff = StaleDiff(schema_changes=[{"change": "removed", "table": "t", "column": "c", "detail": ""}])
        assert diff.summary_parts() == ["1 column removed"]

    def test_changed_column_type(self):
        diff = StaleDiff(schema_changes=[{"change": "changed", "table": "t", "column": "c", "detail": ""}])
        assert diff.summary_parts() == ["1 column type changed"]

    def test_added_test(self):
        diff = StaleDiff(quality_changes=[{"change": "added", "element": "t.c", "test_type": "x", "detail": "", "last_result": None}])
        parts = diff.summary_parts()
        assert "1 new test added" in parts

    def test_removed_test(self):
        diff = StaleDiff(quality_changes=[{"change": "removed", "element": "t.c", "test_type": "x", "detail": "", "last_result": None}])
        parts = diff.summary_parts()
        assert "1 test removed" in parts

    def test_governance_change(self):
        diff = StaleDiff(governance_changes=[{"change": "changed", "table": "t", "column": "c", "field": "classification", "detail": ""}])
        assert diff.summary_parts() == ["1 governance field changed"]

    def test_plural_governance_changes(self):
        diff = StaleDiff(governance_changes=[
            {"change": "changed", "table": "t", "column": "c1", "field": "classification", "detail": ""},
            {"change": "changed", "table": "t", "column": "c2", "field": "description", "detail": ""},
        ])
        assert diff.summary_parts() == ["2 governance fields changed"]

    def test_suite_added(self):
        diff = StaleDiff(suite_scope_changes=[{"change": "added", "suite_name": "s"}])
        assert diff.summary_parts() == ["1 suite added to contract"]

    def test_suite_removed(self):
        diff = StaleDiff(suite_scope_changes=[{"change": "removed", "suite_name": "s"}])
        assert diff.summary_parts() == ["1 suite removed from contract"]

    def test_multiple_categories_combined(self):
        diff = StaleDiff(
            schema_changes=[{"change": "added", "table": "t", "column": "c", "detail": ""}],
            quality_changes=[{"change": "removed", "element": "t.c", "test_type": "x", "detail": "", "last_result": None}],
        )
        parts = diff.summary_parts()
        assert "1 new column detected" in parts
        assert "1 test removed" in parts
        assert len(parts) == 2


# ---------------------------------------------------------------------------
# Test_StaleDiffIsEmpty
# ---------------------------------------------------------------------------

class Test_StaleDiffIsEmpty:
    def test_is_empty_when_no_changes(self):
        assert StaleDiff().is_empty is True

    def test_not_empty_with_schema_changes(self):
        diff = StaleDiff(schema_changes=[{"change": "added", "table": "t", "column": "c", "detail": ""}])
        assert diff.is_empty is False

    def test_not_empty_with_quality_changes(self):
        diff = StaleDiff(quality_changes=[{"change": "removed", "element": "t.c", "test_type": "x", "detail": "", "last_result": None}])
        assert diff.is_empty is False


# ---------------------------------------------------------------------------
# Test_RenderStalenessBanner
# ---------------------------------------------------------------------------

class Test_RenderStalenessBanner:
    def _stale_diff_with_schema(self, n: int = 1) -> StaleDiff:
        return StaleDiff(schema_changes=[
            {"change": "added", "table": "t", "column": f"c{i}", "detail": ""}
            for i in range(n)
        ])

    def test_returns_immediately_when_dismissed(self):
        dismissed_key = "dc_stale_dismissed:abc"
        with patch("testgen.ui.views.data_contract.st") as mock_st:
            mock_st.session_state = {dismissed_key: True}
            _render_staleness_banner(
                version_record={"version": 1, "saved_at": datetime(2026, 1, 1)},
                stale_diff=self._stale_diff_with_schema(),
                contract_id="abc",
                dismissed_key=dismissed_key,
            )
            mock_st.warning.assert_not_called()

    def test_calls_st_warning_with_version_and_date(self):
        with patch("testgen.ui.views.data_contract.st") as mock_st, \
             patch("testgen.ui.views.data_contract.safe_rerun"):
            mock_st.session_state = {}
            col1, col2 = MagicMock(), MagicMock()
            col1.button.return_value = False
            col2.button.return_value = False
            mock_st.columns.return_value = (col1, col2)

            _render_staleness_banner(
                version_record={"version": 3, "saved_at": datetime(2026, 1, 15)},
                stale_diff=self._stale_diff_with_schema(),
                contract_id="tg-1",
                dismissed_key="dc_stale_dismissed:tg-1",
            )

            mock_st.warning.assert_called_once()
            warning_text = mock_st.warning.call_args[0][0]
            assert "version 3" in warning_text
            assert "Jan 15, 2026" in warning_text

    def test_uses_unknown_date_when_no_saved_at(self):
        with patch("testgen.ui.views.data_contract.st") as mock_st, \
             patch("testgen.ui.views.data_contract.safe_rerun"):
            mock_st.session_state = {}
            col1, col2 = MagicMock(), MagicMock()
            col1.button.return_value = False
            col2.button.return_value = False
            mock_st.columns.return_value = (col1, col2)

            _render_staleness_banner(
                version_record={"version": 2},
                stale_diff=self._stale_diff_with_schema(),
                contract_id="tg-2",
                dismissed_key="dc_stale_dismissed:tg-2",
            )

            warning_text = mock_st.warning.call_args[0][0]
            assert "unknown date" in warning_text

    def test_warning_includes_summary_parts(self):
        with patch("testgen.ui.views.data_contract.st") as mock_st, \
             patch("testgen.ui.views.data_contract.safe_rerun"):
            mock_st.session_state = {}
            col1, col2 = MagicMock(), MagicMock()
            col1.button.return_value = False
            col2.button.return_value = False
            mock_st.columns.return_value = (col1, col2)

            diff = self._stale_diff_with_schema(n=2)
            _render_staleness_banner(
                version_record={"version": 1, "saved_at": datetime(2026, 3, 1)},
                stale_diff=diff,
                contract_id="tg-3",
                dismissed_key="dc_stale_dismissed:tg-3",
            )

            warning_text = mock_st.warning.call_args[0][0]
            assert "2 new columns detected" in warning_text

    def test_dismiss_button_sets_dismissed_key(self):
        dismissed_key = "dc_stale_dismissed:tg-4"
        with patch("testgen.ui.views.data_contract.st") as mock_st, \
             patch("testgen.ui.views.data_contract.safe_rerun") as mock_rerun:
            session = {}
            mock_st.session_state = session
            col1, col2 = MagicMock(), MagicMock()
            col1.button.return_value = False
            col2.button.return_value = True  # Dismiss clicked
            mock_st.columns.return_value = (col1, col2)

            _render_staleness_banner(
                version_record={"version": 1, "saved_at": datetime(2026, 3, 1)},
                stale_diff=self._stale_diff_with_schema(),
                contract_id="tg-4",
                dismissed_key=dismissed_key,
            )

            assert session[dismissed_key] is True
            mock_rerun.assert_called_once()
