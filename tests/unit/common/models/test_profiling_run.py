from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.profiling_run import ProfilingRun

pytestmark = pytest.mark.unit

MODULE = "testgen.common.models.profiling_run"


@pytest.fixture
def mock_session():
    session = MagicMock()
    with patch(f"{MODULE}.get_current_session", return_value=session):
        yield session


def _compiled(mock_session) -> str:
    query = mock_session.scalar.call_args[0][0]
    return str(query.compile(compile_kwargs={"literal_binds": True}))


# --- latest_readable_id ---


def test_only_completed_runs_are_eligible(mock_session):
    """profile_results rows are committed per column while a run is in flight, so a running,
    interrupted or paused run holds a partial set and must never resolve as the latest."""
    ProfilingRun.latest_readable_id(uuid4())

    sql = _compiled(mock_session)
    assert "job_executions.status = 'completed'" in sql


def test_pick_is_tie_broken_by_id(mock_session):
    ProfilingRun.latest_readable_id(uuid4())

    sql = _compiled(mock_session)
    order_by = sql.split("ORDER BY")[1]
    assert "profiling_runs.profiling_starttime DESC" in order_by
    assert "profiling_runs.id DESC" in order_by
    assert "LIMIT 1" in sql


def test_as_of_date_compares_calendar_dates(mock_session):
    """Must stay identical to the generation templates' `run_date::DATE <= :AS_OF_DATE ::DATE`:
    a date-level comparison, so a run started later on the as-of date still counts."""
    ProfilingRun.latest_readable_id(uuid4(), datetime(2026, 7, 29, 14, 23, 11, tzinfo=UTC))

    sql = _compiled(mock_session)
    assert "CAST(profiling_runs.profiling_starttime AS DATE) <= '2026-07-29'" in sql
    # A bare instant comparison would silently exclude runs from later that same day.
    assert "profiling_starttime < " not in sql


def test_as_of_date_bound_is_omitted_when_not_given(mock_session):
    ProfilingRun.latest_readable_id(uuid4())

    assert "AS DATE" not in _compiled(mock_session)


def test_finishing_run_is_eligible_alongside_completed_runs(mock_session):
    """A run whose work is done but whose job execution is still 'running' -- the caller is
    inside it -- must be selectable, since nothing else can identify it yet."""
    finishing = uuid4()
    ProfilingRun.latest_readable_id(uuid4(), finishing_run_id=finishing)

    sql = _compiled(mock_session)
    assert f"job_executions.status = 'completed' OR profiling_runs.id = '{finishing.hex}'" in sql


def test_finishing_run_does_not_bypass_the_as_of_date(mock_session):
    """A table group with a profiling delay generates from an older run on purpose, including
    right after a run finishes. The caller's run id relaxes the status check, not the window."""
    ProfilingRun.latest_readable_id(
        uuid4(),
        datetime(2026, 7, 26, 9, 0, 0, tzinfo=UTC),
        finishing_run_id=uuid4(),
    )

    sql = _compiled(mock_session)
    assert "CAST(profiling_runs.profiling_starttime AS DATE) <= '2026-07-26'" in sql
