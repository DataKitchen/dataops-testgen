from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from testgen.common.date_service import as_iso_timestamp, get_now_as_iso_timestamp

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
