"""Tests for holiday-code validation in ``common/holiday_service.py``."""

import pytest

from testgen.common.holiday_service import (
    canonicalize_holiday_code,
    is_supported_holiday_code,
    list_holiday_calendars,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("code", ["US", "GB", "CA", "USA", "NYSE", "ECB", "  us  "])
def test_supported_codes(code):
    """ISO country codes, uppercase aliases, and financial-market codes resolve."""
    assert is_supported_holiday_code(code) is True


@pytest.mark.parametrize(
    "code",
    [
        "US_FEDERAL",   # not a holidays-package calendar
        "CA_STAT",
        "Canada",       # the upper-cased "CANADA" is not a valid key — documented quirk
        "NOTAREALCODE",
        "",
        "   ",
    ],
)
def test_unsupported_codes(code):
    assert is_supported_holiday_code(code) is False


def test_list_holiday_calendars_shape():
    calendars = list_holiday_calendars()
    assert calendars
    assert all(set(calendar) == {"label", "value"} for calendar in calendars)


def test_list_holiday_calendars_pinned_first():
    """US-related calendars lead the list, in the pinned order, ahead of the alphabetical rest."""
    calendars = list_holiday_calendars()
    assert calendars[0] == {"label": "United States", "value": "US"}
    assert calendars[1] == {"label": "New York Stock Exchange", "value": "XNYS"}


def test_list_holiday_calendars_rest_is_alphabetical():
    labels = [calendar["label"] for calendar in list_holiday_calendars()[2:]]
    assert labels == sorted(labels, key=str.lower)


def test_list_holiday_calendars_values_are_resolvable():
    """Every offered code resolves, so the picker can never surface a silent no-op option."""
    assert all(is_supported_holiday_code(calendar["value"]) for calendar in list_holiday_calendars())


def test_list_holiday_calendars_values_are_unique():
    values = [calendar["value"] for calendar in list_holiday_calendars()]
    assert len(values) == len(set(values))


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("US", "US"),
        ("us", "US"),
        ("USA", "US"),          # alpha-3 alias
        ("NYSE", "XNYS"),       # market alias -> canonical MIC
        ("ecb", "XECB"),
        ("  gb  ", "GB"),
        ("NOTAREALCODE", "NOTAREALCODE"),  # unrecognized passes through, upper-cased
    ],
)
def test_canonicalize_holiday_code(code, expected):
    assert canonicalize_holiday_code(code) == expected


def test_canonicalize_matches_picker_values():
    """Every canonical code the picker offers canonicalizes to itself (stable across surfaces)."""
    for calendar in list_holiday_calendars():
        assert canonicalize_holiday_code(calendar["value"]) == calendar["value"]
