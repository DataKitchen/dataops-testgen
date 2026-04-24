from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from testgen.common.date_service import (
    as_iso_timestamp,
    get_now_as_iso_timestamp,
    parse_fuzzy_date,
    parse_since,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "value, expected",
    [
        (datetime(2024, 3, 15, 10, 30, 45), "2024-03-15T10:30:45Z"),
        (datetime(2024, 1, 1, 0, 0, 0), "2024-01-01T00:00:00Z"),
        (None, None),
    ],
)
def test_as_iso_timestamp(value, expected):
    assert as_iso_timestamp(value) == expected


def test_get_now_as_iso_timestamp():
    with patch("testgen.common.date_service.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        mock_dt.strftime = datetime.strftime
        result = get_now_as_iso_timestamp()

    assert result == "2024-06-15T12:00:00Z"


class Test_parse_fuzzy_date:
    def test_parses_string_date(self):
        result = parse_fuzzy_date("2024-03-15 10:30:45")
        assert result == datetime(2024, 3, 15, 10, 30, 45)

    def test_parses_unix_timestamp_seconds(self):
        result = parse_fuzzy_date(1710500000)
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_parses_unix_timestamp_milliseconds(self):
        result = parse_fuzzy_date(1710500000000)
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_parses_float_timestamp(self):
        result = parse_fuzzy_date(1710500000.0)
        assert isinstance(result, datetime)

    def test_returns_value_unchanged_for_other_types(self):
        dt = datetime(2024, 1, 1)
        assert parse_fuzzy_date(dt) is dt

    def test_returns_none_for_none(self):
        assert parse_fuzzy_date(None) is None


@pytest.mark.parametrize(
    "expression, expected_date",
    [
        # N calendar days ending today inclusive → start = today - (N-1).
        # Today in the test is 2026-04-22 (Wed).
        ("1 day", date(2026, 4, 22)),
        ("7 days", date(2026, 4, 16)),
        ("7d", date(2026, 4, 16)),
        ("14 days", date(2026, 4, 9)),
        # N*7 calendar days ending today inclusive.
        ("1 week", date(2026, 4, 16)),
        ("2 weeks", date(2026, 4, 9)),
        ("2w", date(2026, 4, 9)),
        # Whitespace tolerated.
        ("  5 days  ", date(2026, 4, 18)),
    ],
)
def test_parse_since_fixed_duration_units(expression, expected_date):
    """Day/week expressions are calendar-day-aligned and return a plain date."""
    result = parse_since(expression, today=date(2026, 4, 22))
    assert result == expected_date
    assert isinstance(result, date) and not isinstance(result, datetime)


@pytest.mark.parametrize(
    "expression, today, expected_date",
    [
        # Same day-of-month in target: 04/22 - 2 months → 02/22
        ("2 months", date(2026, 4, 22), date(2026, 2, 22)),
        # Single-month shorthand
        ("1 month", date(2026, 4, 22), date(2026, 3, 22)),
        # Clamp: 03/31 - 1 month → 02/28 (Feb has no 31st)
        ("1 month", date(2026, 3, 31), date(2026, 2, 28)),
        # Year underflow
        ("1 month", date(2026, 1, 15), date(2025, 12, 15)),
        # Multi-year underflow
        ("14 months", date(2026, 1, 15), date(2024, 11, 15)),
        # "mo" shorthand
        ("3mo", date(2026, 4, 22), date(2026, 1, 22)),
    ],
)
def test_parse_since_calendar_months(expression, today, expected_date):
    assert parse_since(expression, today=today) == expected_date


def test_parse_since_iso_date():
    assert parse_since("2026-04-01") == date(2026, 4, 1)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "bogus",
        "days",
        "3 fortnights",
        "yesterday",
        # Time-of-day is not accepted — use ISO date only.
        "2026-04-01T12:30:00",
        "2026-04-01T12:30:00Z",
    ],
)
def test_parse_since_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_since(bad)
