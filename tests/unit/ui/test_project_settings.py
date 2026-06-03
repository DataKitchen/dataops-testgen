from unittest.mock import MagicMock, Mock, patch

import pytest

from testgen.common.enums import JobKey
from testgen.ui.views.project_settings import ProjectSettingsPage

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.views.project_settings"


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.scalars.return_value.all.return_value = []
    with patch("testgen.common.models.Session", return_value=session):
        yield session


def _make_page(use_dq_score_weights=True, data_retention_enabled=False, data_retention_days=None):
    page = ProjectSettingsPage.__new__(ProjectSettingsPage)
    page.project = MagicMock()
    page.project.use_dq_score_weights = use_dq_score_weights
    page.project.project_name = "My Project"
    page.project.data_retention_enabled = data_retention_enabled
    page.project.data_retention_days = data_retention_days
    return page


def test_update_project_submits_recalculate_job_when_weights_toggled_on(mock_session):
    page = _make_page(use_dq_score_weights=False)

    with patch(f"{MODULE}.JobExecution") as mock_je:
        page.update_project("proj", {"name": "My Project", "use_dq_score_weights": True})

    mock_je.submit.assert_called_once_with(
        job_key=JobKey.recalculate_project_scores,
        kwargs={"project_code": "proj"},
        source="ui",
        project_code="proj",
    )


def test_update_project_submits_recalculate_job_when_weights_toggled_off(mock_session):
    page = _make_page(use_dq_score_weights=True)

    with patch(f"{MODULE}.JobExecution") as mock_je:
        page.update_project("proj", {"name": "My Project", "use_dq_score_weights": False})

    mock_je.submit.assert_called_once_with(
        job_key=JobKey.recalculate_project_scores,
        kwargs={"project_code": "proj"},
        source="ui",
        project_code="proj",
    )


def test_update_project_does_not_submit_job_when_weights_unchanged(mock_session):
    page = _make_page(use_dq_score_weights=True)

    with patch(f"{MODULE}.JobExecution") as mock_je:
        page.update_project("proj", {"name": "My Project", "use_dq_score_weights": True})

    mock_je.submit.assert_not_called()


def test_update_project_saves_weight_setting(mock_session):
    page = _make_page(use_dq_score_weights=False)

    with patch(f"{MODULE}.JobExecution"):
        page.update_project("proj", {"name": "My Project", "use_dq_score_weights": True})

    assert page.project.use_dq_score_weights is True
    page.project.save.assert_called_once()


def test_update_project_raises_on_duplicate_name(mock_session):
    page = _make_page()
    mock_session.scalars.return_value.all.return_value = [
        MagicMock(project_name="Other Project"),
    ]

    with (
        patch(f"{MODULE}.select_projects_where") as mock_select,
        pytest.raises(ValueError, match="Other Project"),
    ):
        mock_select.return_value = [MagicMock(project_name="Other Project")]
        page.update_project("proj", {"name": "Other Project", "use_dq_score_weights": True})


# ─── Data retention ──────────────────────────────────────────────────


def test_update_project_upserts_schedule_when_retention_enabled(mock_session):
    page = _make_page(data_retention_enabled=False)
    payload = {
        "name": "My Project",
        "use_dq_score_weights": True,
        "data_retention_enabled": True,
        "data_retention_days": 90,
        "retention_cron_expr": "0 2 * * *",
        "retention_cron_tz": "America/New_York",
    }

    with (
        patch(f"{MODULE}.JobExecution"),
        patch(f"{MODULE}.JobSchedule") as mock_schedule,
    ):
        page.update_project("proj", payload)

    mock_schedule.upsert_for_retention.assert_called_once_with(
        project_code="proj",
        retention_days=90,
        cron_expr="0 2 * * *",
        cron_tz="America/New_York",
    )
    mock_schedule.delete_for_retention.assert_not_called()
    assert page.project.data_retention_enabled is True
    assert page.project.data_retention_days == 90


def test_update_project_deletes_schedule_when_retention_disabled(mock_session):
    """No-op cleanup contract: disabling retention removes the schedule so the
    cleanup job never fires for this project."""
    page = _make_page(data_retention_enabled=True, data_retention_days=180)
    payload = {
        "name": "My Project",
        "use_dq_score_weights": True,
        "data_retention_enabled": False,
    }

    with (
        patch(f"{MODULE}.JobExecution"),
        patch(f"{MODULE}.JobSchedule") as mock_schedule,
    ):
        page.update_project("proj", payload)

    mock_schedule.delete_for_retention.assert_called_once_with("proj")
    mock_schedule.upsert_for_retention.assert_not_called()
    assert page.project.data_retention_enabled is False
    # When disabled the days column is nulled out (matches the migration's nullable column).
    assert page.project.data_retention_days is None


def test_update_project_uses_default_days_when_missing(mock_session):
    """Enabling retention without an explicit days value falls back to the page's
    DEFAULT_RETENTION_DAYS constant (180) so the schedule is still well-formed."""
    page = _make_page(data_retention_enabled=False)
    payload = {
        "name": "My Project",
        "use_dq_score_weights": True,
        "data_retention_enabled": True,
        # data_retention_days omitted
        "retention_cron_expr": "0 1 * * *",
        "retention_cron_tz": "UTC",
    }

    with (
        patch(f"{MODULE}.JobExecution"),
        patch(f"{MODULE}.JobSchedule") as mock_schedule,
    ):
        page.update_project("proj", payload)

    kwargs = mock_schedule.upsert_for_retention.call_args.kwargs
    assert kwargs["retention_days"] == 180
