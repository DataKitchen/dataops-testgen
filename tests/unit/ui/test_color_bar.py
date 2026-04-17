"""
Unit tests for _color_bar_html in data_contracts_list.py.
pytest -m unit tests/unit/ui/test_color_bar.py
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Mock Streamlit component machinery before importing app code
# ---------------------------------------------------------------------------

import streamlit.components.v2 as _sv2
_sv2.component = MagicMock(return_value=MagicMock())
sys.modules.setdefault("testgen.ui.components.widgets.testgen_component", MagicMock())

from testgen.ui.views.data_contracts_list import _color_bar_html  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class Test_ColorBarHtml_NoRun:
    def test_gray_bar_when_all_counts_zero(self):
        html = _color_bar_html(0, 0, 0)
        assert "#cbd5e1" in html

    def test_no_flex_container_when_no_run(self):
        html = _color_bar_html(0, 0, 0)
        assert "display:flex" not in html

    def test_single_div_when_no_run(self):
        html = _color_bar_html(0, 0, 0)
        assert html.count("<div") == 1


class Test_ColorBarHtml_AllPassed:
    def test_green_segment_present(self):
        html = _color_bar_html(10, 0, 0)
        assert "#22c55e" in html

    def test_no_orange_when_no_warnings(self):
        html = _color_bar_html(10, 0, 0)
        assert "#f59e0b" not in html

    def test_no_red_when_no_failures(self):
        html = _color_bar_html(10, 0, 0)
        assert "#ef4444" not in html

    def test_flex_container_present(self):
        html = _color_bar_html(10, 0, 0)
        assert "display:flex" in html


class Test_ColorBarHtml_Mixed:
    def test_all_three_colors_present(self):
        html = _color_bar_html(3, 1, 1)
        assert "#22c55e" in html
        assert "#f59e0b" in html
        assert "#ef4444" in html

    def test_flex_values_match_counts(self):
        html = _color_bar_html(5, 2, 3)
        assert "flex:5" in html
        assert "flex:2" in html
        assert "flex:3" in html

    def test_segment_order_passed_warning_failed(self):
        html = _color_bar_html(3, 1, 1)
        green_pos  = html.index("#22c55e")
        orange_pos = html.index("#f59e0b")
        red_pos    = html.index("#ef4444")
        assert green_pos < orange_pos < red_pos

    def test_zero_warning_segment_omitted(self):
        html = _color_bar_html(5, 0, 3)
        assert "#f59e0b" not in html


class Test_ColorBarHtml_FailedOnly:
    def test_only_red_segment_when_all_failed(self):
        html = _color_bar_html(0, 0, 7)
        assert "#ef4444" in html
        assert "#22c55e" not in html
        assert "#f59e0b" not in html

    def test_flex_value_matches_failed_count(self):
        html = _color_bar_html(0, 0, 7)
        assert "flex:7" in html
