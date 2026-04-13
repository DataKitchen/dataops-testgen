"""
Unit tests for _check_contract_prerequisites in data_contract.py.

pytest -m unit tests/unit/ui/test_contract_first_time_flow.py
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

import streamlit.components.v2 as _sv2
_sv2.component = MagicMock(return_value=MagicMock())
sys.modules.setdefault("testgen.ui.components.widgets.testgen_component", MagicMock())

# Strip @with_database_session so the function can be called without a live DB
sys.modules.setdefault(
    "testgen.ui.views.data_contract",
    MagicMock(),
)

# We want the real module, not a MagicMock — remove the placeholder if it was
# just set, then do a real import with with_database_session patched out.
if isinstance(sys.modules.get("testgen.ui.views.data_contract"), MagicMock):
    del sys.modules["testgen.ui.views.data_contract"]

with patch("testgen.common.models.with_database_session", lambda f: f):
    from testgen.ui.views.data_contract import _check_contract_prerequisites  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TG_ID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
_SCHEMA = "testgen"

_EMPTY: list = []


def _profiling_row(last_run):
    return [{"last_run": last_run}]


def _suite_row(ct):
    return [{"ct": ct}]


def _meta_row(total, with_meta):
    return [{"total": total, "with_meta": with_meta}]


# ---------------------------------------------------------------------------
# Test_CheckContractPrerequisites
# ---------------------------------------------------------------------------

class Test_CheckContractPrerequisites:

    # --- shared patch targets ---
    _FETCH = "testgen.ui.views.data_contract.fetch_dict_from_db"
    _SCHEMA = "testgen.ui.views.data_contract.get_tg_schema"

    def _call(self, side_effects):
        with patch(self._SCHEMA, return_value="testgen"), \
             patch(self._FETCH, side_effect=side_effects) as mock_fetch:
            result = _check_contract_prerequisites(_TG_ID)
            return result, mock_fetch

    # 1. has_profiling=True when a profiling run exists
    def test_has_profiling_true_when_run_exists(self):
        ts = datetime(2024, 6, 1, 12, 0, 0)
        result, _ = self._call([
            _profiling_row(ts),
            _suite_row(0),
            _meta_row(0, 0),
        ])
        assert result["has_profiling"] is True
        assert result["last_profiling"] == ts

    # 2. has_profiling=False when last_run is None
    def test_has_profiling_false_when_no_run(self):
        result, _ = self._call([
            _profiling_row(None),
            _suite_row(0),
            _meta_row(0, 0),
        ])
        assert result["has_profiling"] is False
        assert result["last_profiling"] is None

    # 3. has_profiling=False when profiling query returns []
    def test_has_profiling_false_when_db_empty(self):
        result, _ = self._call([
            _EMPTY,
            _suite_row(0),
            _meta_row(0, 0),
        ])
        assert result["has_profiling"] is False
        assert result["last_profiling"] is None

    # 4. has_suites=True when suite count is positive
    def test_has_suites_true_when_count_positive(self):
        result, _ = self._call([
            _profiling_row(None),
            _suite_row(5),
            _meta_row(0, 0),
        ])
        assert result["has_suites"] is True
        assert result["suite_ct"] == 5

    # 5. has_suites=False when suite count is zero
    def test_has_suites_false_when_count_zero(self):
        result, _ = self._call([
            _profiling_row(None),
            _suite_row(0),
            _meta_row(0, 0),
        ])
        assert result["has_suites"] is False
        assert result["suite_ct"] == 0

    # 6. meta_pct calculated correctly
    def test_meta_pct_calculated_correctly(self):
        result, _ = self._call([
            _profiling_row(None),
            _suite_row(0),
            _meta_row(100, 40),
        ])
        assert result["meta_pct"] == 40

    # 7. meta_pct=0 when total=0 (no division by zero)
    def test_meta_pct_zero_when_no_columns(self):
        result, _ = self._call([
            _profiling_row(None),
            _suite_row(0),
            _meta_row(0, 0),
        ])
        assert result["meta_pct"] == 0

    # 8. meta_pct=100 when all columns have metadata
    def test_meta_pct_hundred_when_all_have_meta(self):
        result, _ = self._call([
            _profiling_row(None),
            _suite_row(0),
            _meta_row(10, 10),
        ])
        assert result["meta_pct"] == 100

    # 9. all False/zero when every query returns []
    def test_returns_all_false_when_all_empty(self):
        result, _ = self._call([_EMPTY, _EMPTY, _EMPTY])
        assert result["has_profiling"] is False
        assert result["last_profiling"] is None
        assert result["has_suites"] is False
        assert result["suite_ct"] == 0
        assert result["meta_pct"] == 0

    # 10. table_group_id is forwarded to at least one DB call
    def test_table_group_id_passed_as_param(self):
        _, mock_fetch = self._call([
            _profiling_row(None),
            _suite_row(0),
            _meta_row(0, 0),
        ])
        # At least one of the three calls must carry tg_id in its params
        tg_id_found = any(
            call.kwargs.get("params", {}).get("tg_id") == _TG_ID
            or (len(call.args) > 1 and call.args[1].get("tg_id") == _TG_ID)
            for call in mock_fetch.call_args_list
        )
        assert tg_id_found, "tg_id was not forwarded to any fetch_dict_from_db call"
