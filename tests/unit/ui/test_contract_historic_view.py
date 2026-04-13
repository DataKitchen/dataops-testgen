"""
Unit tests for the historic / version-picker view logic in data_contract.py.

pytest -m unit tests/unit/ui/test_contract_historic_view.py
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

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

from datetime import datetime  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers that replicate inline expressions from data_contract.py
# ---------------------------------------------------------------------------

def _is_latest(versions: list[dict], version_record: dict) -> bool:
    """Replicates: is_latest = (version_record["version"] == versions[0]["version"]) if versions else True"""
    return (version_record["version"] == versions[0]["version"]) if versions else True


def _version_labels(versions: list[dict]) -> list[str]:
    """Replicates the version_labels list comprehension (lines 468-477)."""
    return [
        (
            f"Version {v['version']}  ·  {v['saved_at'].strftime('%b %d %Y %H:%M') if v.get('saved_at') else ''}  "
            f"{'— ' + v['label'] if v.get('label') else ''}  (latest)"
            if i == 0 else
            f"Version {v['version']}  ·  {v['saved_at'].strftime('%b %d %Y %H:%M') if v.get('saved_at') else ''}  "
            f"{'— ' + v['label'] if v.get('label') else ''}"
        )
        for i, v in enumerate(versions)
    ]


def _banner_text(version_record: dict, versions: list[dict]) -> str:
    """Replicates the f-string body of the historic read-only st.info call (lines 549-555)."""
    saved_at = version_record.get("saved_at")
    saved_str = saved_at.strftime("%b %d, %Y at %H:%M") if saved_at else ""
    label_str = f' "{version_record["label"]}"' if version_record.get("label") else ""
    return (
        f"📋 Viewing version {version_record['version']}{label_str} — saved {saved_str}. "
        f"This is a read-only snapshot. The latest is version {versions[0]['version']}."
    )


# ---------------------------------------------------------------------------
# Test_IsLatestLogic
# ---------------------------------------------------------------------------

class Test_IsLatestLogic:
    def test_is_latest_when_version_matches_first(self):
        versions = [{"version": 3}, {"version": 2}]
        record = {"version": 3}
        assert _is_latest(versions, record) is True

    def test_not_latest_when_viewing_older(self):
        versions = [{"version": 3}, {"version": 2}, {"version": 1}]
        record = {"version": 1}
        assert _is_latest(versions, record) is False

    def test_is_latest_when_only_one_version(self):
        versions = [{"version": 0}]
        record = {"version": 0}
        assert _is_latest(versions, record) is True

    def test_is_latest_when_versions_empty(self):
        versions: list[dict] = []
        record = {"version": 0}
        assert _is_latest(versions, record) is True

    def test_not_latest_second_version(self):
        versions = [{"version": 5}, {"version": 4}]
        record = {"version": 4}
        assert _is_latest(versions, record) is False


# ---------------------------------------------------------------------------
# Test_VersionLabelFormatting
# ---------------------------------------------------------------------------

class Test_VersionLabelFormatting:
    def test_first_version_has_latest_marker(self):
        versions = [
            {"version": 3, "saved_at": datetime(2026, 3, 1, 9, 0), "label": None},
            {"version": 2, "saved_at": datetime(2026, 2, 1, 9, 0), "label": None},
        ]
        labels = _version_labels(versions)
        assert "(latest)" in labels[0]

    def test_older_versions_do_not_have_latest(self):
        versions = [
            {"version": 3, "saved_at": datetime(2026, 3, 1, 9, 0), "label": None},
            {"version": 2, "saved_at": datetime(2026, 2, 1, 9, 0), "label": None},
            {"version": 1, "saved_at": datetime(2026, 1, 1, 9, 0), "label": None},
        ]
        labels = _version_labels(versions)
        for label in labels[1:]:
            assert "(latest)" not in label

    def test_label_included_when_present(self):
        versions = [
            {"version": 2, "saved_at": datetime(2026, 3, 1, 9, 0), "label": "release-1.0"},
        ]
        labels = _version_labels(versions)
        assert "— release-1.0" in labels[0]

    def test_label_omitted_when_none(self):
        versions = [
            {"version": 2, "saved_at": datetime(2026, 3, 1, 9, 0), "label": None},
        ]
        labels = _version_labels(versions)
        assert "—" not in labels[0]

    def test_saved_at_formatted_correctly(self):
        versions = [
            {"version": 1, "saved_at": datetime(2026, 3, 15, 10, 30), "label": None},
        ]
        labels = _version_labels(versions)
        assert "Mar 15 2026 10:30" in labels[0]

    def test_saved_at_empty_string_when_missing(self):
        versions = [
            {"version": 1, "label": None},  # no "saved_at" key
        ]
        # should not raise; saved_at portion should be blank
        labels = _version_labels(versions)
        assert isinstance(labels[0], str)
        assert "Version 1" in labels[0]


# ---------------------------------------------------------------------------
# Test_VersionQueryParamParsing
# ---------------------------------------------------------------------------

class Test_VersionQueryParamParsing:
    def _parse(self, raw_ver: str | None) -> int | None:
        """Replicates the query-param parsing block (lines 408-412)."""
        requested_version: int | None = None
        if raw_ver is not None:
            try:
                requested_version = int(raw_ver)
            except ValueError:
                requested_version = None
        return requested_version

    def test_valid_string_parses_to_int(self):
        assert self._parse("3") == 3

    def test_invalid_string_returns_none(self):
        assert self._parse("abc") is None

    def test_none_query_param_stays_none(self):
        assert self._parse(None) is None

    def test_version_zero_parses_correctly(self):
        assert self._parse("0") == 0


# ---------------------------------------------------------------------------
# Test_HistoricBannerText
# ---------------------------------------------------------------------------

class Test_HistoricBannerText:
    def test_banner_text_includes_version_number(self):
        version_record = {"version": 2, "saved_at": datetime(2026, 1, 20, 14, 30)}
        versions = [{"version": 5}, {"version": 2}]
        text = _banner_text(version_record, versions)
        assert "version 2" in text

    def test_banner_text_includes_saved_at_formatted(self):
        version_record = {"version": 2, "saved_at": datetime(2026, 1, 20, 14, 30)}
        versions = [{"version": 5}, {"version": 2}]
        text = _banner_text(version_record, versions)
        assert "Jan 20, 2026 at 14:30" in text

    def test_banner_text_includes_latest_version_number(self):
        version_record = {"version": 2, "saved_at": datetime(2026, 1, 20, 14, 30)}
        versions = [{"version": 5}, {"version": 2}]
        text = _banner_text(version_record, versions)
        assert "latest is version 5" in text

    def test_banner_text_includes_label_when_present(self):
        version_record = {"version": 2, "saved_at": datetime(2026, 1, 20, 14, 30), "label": "approved"}
        versions = [{"version": 5}, {"version": 2}]
        text = _banner_text(version_record, versions)
        assert '"approved"' in text

    def test_banner_text_no_label_when_absent(self):
        version_record = {"version": 2, "saved_at": datetime(2026, 1, 20, 14, 30)}
        versions = [{"version": 5}, {"version": 2}]
        text = _banner_text(version_record, versions)
        # no label key → no extra quoted string before the em-dash
        assert '"' not in text.split("—")[0]
