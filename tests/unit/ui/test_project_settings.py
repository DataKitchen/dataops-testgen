from unittest.mock import MagicMock, Mock, patch

import pytest

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


def _make_page(use_dq_score_weights=True):
    page = ProjectSettingsPage.__new__(ProjectSettingsPage)
    page.project = MagicMock()
    page.project.use_dq_score_weights = use_dq_score_weights
    page.project.project_name = "My Project"
    return page


def test_update_project_submits_recalculate_job_when_weights_toggled_on(mock_session):
    page = _make_page(use_dq_score_weights=False)

    with patch(f"{MODULE}.JobExecution") as mock_je:
        page.update_project("proj", {"name": "My Project", "use_dq_score_weights": True})

    mock_je.submit.assert_called_once_with(
        job_key="recalculate-project-scores",
        kwargs={"project_code": "proj"},
        source="user",
        project_code="proj",
    )


def test_update_project_submits_recalculate_job_when_weights_toggled_off(mock_session):
    page = _make_page(use_dq_score_weights=True)

    with patch(f"{MODULE}.JobExecution") as mock_je:
        page.update_project("proj", {"name": "My Project", "use_dq_score_weights": False})

    mock_je.submit.assert_called_once_with(
        job_key="recalculate-project-scores",
        kwargs={"project_code": "proj"},
        source="user",
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
        patch(f"{MODULE}.Project") as mock_project_cls,
        pytest.raises(ValueError, match="Other Project"),
    ):
        mock_project_cls.select_where.return_value = [MagicMock(project_name="Other Project")]
        page.update_project("proj", {"name": "Other Project", "use_dq_score_weights": True})
