from unittest.mock import MagicMock, patch

import pytest

from testgen.common.enums import JobKey
from testgen.common.models.scheduler import (
    DEFAULT_DATA_CLEANUP_CRON,
    JobSchedule,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.common.models.scheduler"


@pytest.fixture
def mock_session():
    session = MagicMock()
    with patch(f"{MODULE}.get_current_session", return_value=session):
        yield session


# ─── upsert_for_retention ───────────────────────────────────────────


def test_upsert_for_retention_inserts_when_missing(mock_session):
    """No existing schedule for (project, JobKey.run_data_cleanup) → INSERT path:
    creates a fresh JobSchedule and adds it to the session."""
    mock_session.scalars.return_value.first.return_value = None

    schedule = JobSchedule.upsert_for_retention(
        project_code="proj",
        retention_days=90,
        cron_expr="0 1 * * *",
        cron_tz="UTC",
    )

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added is schedule
    assert schedule.project_code == "proj"
    assert schedule.key == JobKey.run_data_cleanup
    assert schedule.kwargs == {"project_code": "proj", "retention_days": 90}
    assert schedule.cron_expr == "0 1 * * *"
    assert schedule.cron_tz == "UTC"
    assert schedule.active is True


def test_upsert_for_retention_updates_when_present(mock_session):
    """Existing schedule for the same (project, key) → UPDATE path: mutates in
    place; does NOT add a new row (would otherwise violate the table's
    UNIQUE constraint and duplicate schedules per project)."""
    existing = JobSchedule(
        project_code="proj",
        key=JobKey.run_data_cleanup,
        kwargs={"project_code": "proj", "retention_days": 180},
        cron_expr="0 1 * * *",
        cron_tz="UTC",
        active=False,
    )
    mock_session.scalars.return_value.first.return_value = existing

    result = JobSchedule.upsert_for_retention(
        project_code="proj",
        retention_days=30,
        cron_expr="0 2 * * *",
        cron_tz="America/New_York",
    )

    mock_session.add.assert_not_called()
    assert result is existing
    assert existing.kwargs == {"project_code": "proj", "retention_days": 30}
    assert existing.cron_expr == "0 2 * * *"
    assert existing.cron_tz == "America/New_York"
    # Re-activated even when the previous schedule had been deactivated
    assert existing.active is True


def test_upsert_for_retention_reactivates_inactive_schedule(mock_session):
    """A specific guard: if a project's retention schedule was disabled (active=False)
    and the user re-enables retention, the upsert flips active back to True."""
    existing = JobSchedule(
        project_code="proj",
        key=JobKey.run_data_cleanup,
        kwargs={},
        cron_expr="0 1 * * *",
        cron_tz="UTC",
        active=False,
    )
    mock_session.scalars.return_value.first.return_value = existing

    JobSchedule.upsert_for_retention(
        project_code="proj",
        retention_days=180,
        cron_expr=DEFAULT_DATA_CLEANUP_CRON,
        cron_tz="UTC",
    )

    assert existing.active is True


def test_upsert_for_retention_does_not_commit(mock_session):
    """Like other model methods: the helper participates in the caller's
    transaction; it must not commit on its own. The save() path is owned by
    the request scope (database_session or safe_rerun)."""
    mock_session.scalars.return_value.first.return_value = None

    JobSchedule.upsert_for_retention(
        project_code="proj",
        retention_days=180,
        cron_expr=DEFAULT_DATA_CLEANUP_CRON,
        cron_tz="UTC",
    )

    mock_session.commit.assert_not_called()


# ─── delete_for_retention ───────────────────────────────────────────


def test_delete_for_retention_executes_scoped_delete(mock_session):
    """Issues a single DELETE filtered to (project_code, JobKey.run_data_cleanup).
    Idempotent — safe to call when no schedule exists (mock_session.execute
    is a no-op)."""
    JobSchedule.delete_for_retention("proj")

    mock_session.execute.assert_called_once()
    stmt = mock_session.execute.call_args.args[0]
    rendered = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "DELETE FROM job_schedules" in rendered
    assert "proj" in rendered
    assert JobKey.run_data_cleanup in rendered


def test_delete_for_retention_does_not_commit(mock_session):
    JobSchedule.delete_for_retention("proj")
    mock_session.commit.assert_not_called()
