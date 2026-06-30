"""Tests for holiday-code validation in ``common/holiday_service.py``."""

import pytest

from testgen.common.holiday_service import is_supported_holiday_code

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
