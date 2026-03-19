from unittest.mock import MagicMock, Mock, patch

import pytest

from testgen.common.models import _current_session_wrapper, database_session, get_current_session

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_thread_local():
    """Ensure thread-local is clean before and after each test."""
    _current_session_wrapper.value = None
    yield
    _current_session_wrapper.value = None


def _make_mock_session():
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    return session


def test_session_cm_creates_and_cleans_up():
    mock_session = _make_mock_session()
    with patch("testgen.common.models.Session", return_value=mock_session):
        with database_session() as session:
            assert session is mock_session
            assert get_current_session() is mock_session

    assert get_current_session() is None


def test_session_cm_reuses_existing():
    existing = MagicMock()
    _current_session_wrapper.value = existing

    with database_session() as session:
        assert session is existing

    # Owning call didn't happen, so thread-local is untouched
    assert get_current_session() is existing


def test_session_cm_commits_on_success():
    mock_session = _make_mock_session()
    with patch("testgen.common.models.Session", return_value=mock_session):
        with database_session():
            pass

    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()


def test_session_cm_rollback_on_exception():
    mock_session = _make_mock_session()
    with patch("testgen.common.models.Session", return_value=mock_session):
        with pytest.raises(ValueError, match="boom"):
            with database_session():
                raise ValueError("boom")

    mock_session.rollback.assert_called_once()
    mock_session.commit.assert_not_called()
    assert get_current_session() is None
