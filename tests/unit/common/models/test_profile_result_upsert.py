from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.profile_result import ProfileResult

pytestmark = pytest.mark.unit

NEW_YORK = timezone(timedelta(hours=-4))


def _written(row: dict) -> dict:
    session = MagicMock()

    @contextmanager
    def database_session():
        yield session

    with patch("testgen.common.models.profile_result.database_session", database_session):
        ProfileResult.upsert(row)
    statement = session.execute.call_args.args[0]
    return statement.compile(dialect=postgresql.dialect()).params


def test_a_zoned_date_from_the_target_keeps_the_wall_time_the_target_reported():
    """A Match Max/Min Date measure renders the column's maximum as the target session's wall time,
    so the baseline must hold that wall time, not the UTC instant."""
    params = _written({
        "max_date": datetime(2026, 10, 4, 22, 30, tzinfo=NEW_YORK),
        "min_date": datetime(2026, 10, 1, 8, 0, tzinfo=NEW_YORK),
    })

    assert params["max_date"] == datetime(2026, 10, 4, 22, 30)
    assert params["min_date"] == datetime(2026, 10, 1, 8, 0)


def test_a_naive_date_from_the_target_is_stored_as_given():
    assert _written({"max_date": datetime(2026, 10, 4, 22, 30)})["max_date"] == datetime(2026, 10, 4, 22, 30)


def test_a_timestamp_testgen_sets_keeps_its_zone():
    run_date = datetime(2026, 10, 5, 2, 30, tzinfo=UTC)
    assert _written({"run_date": run_date})["run_date"] == run_date


def test_an_approximate_percentile_outside_the_range_is_clamped_to_it():
    """On a constant column an approximate percentile can land a rounding error past the minimum or
    maximum, which puts it out of order with the exact range it summarizes."""
    params = _written({
        "min_value": 5.0,
        "max_value": 5.0,
        "percentile_25": 4.999999999999999,
        "percentile_50": 5.0,
        "percentile_75": 5.000000000000001,
    })

    assert (params["percentile_25"], params["percentile_50"], params["percentile_75"]) == (5.0, 5.0, 5.0)


def test_a_percentile_inside_the_range_is_stored_as_given():
    params = _written({"min_value": 1.0, "max_value": 9.0, "percentile_25": 2.5, "percentile_75": 7.25})
    assert (params["percentile_25"], params["percentile_75"]) == (2.5, 7.25)


def test_a_percentile_without_a_range_is_stored_as_given():
    assert _written({"percentile_50": 3.5})["percentile_50"] == 3.5
