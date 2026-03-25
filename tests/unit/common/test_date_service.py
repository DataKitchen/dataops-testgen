from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from testgen.common.date_service import as_iso_timestamp, get_now_as_iso_timestamp, parse_fuzzy_date

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
