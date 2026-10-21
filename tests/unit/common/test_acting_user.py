from unittest.mock import MagicMock, patch

import pytest

from testgen.common import acting_user

pytestmark = pytest.mark.unit


@pytest.fixture
def no_fallbacks():
    with patch.object(acting_user, "_fallbacks", []):
        yield


def _session() -> MagicMock:
    session = MagicMock()
    session.info = {}
    return session


def test_the_user_set_on_the_session_is_the_acting_user(no_fallbacks):
    session = _session()
    with patch.object(acting_user, "get_current_session", return_value=session):
        acting_user.set_acting_username("alice")
        acting_user.register_acting_user_fallback(lambda: "bob")

        assert acting_user.acting_username() == "alice"


def test_a_fallback_answers_when_the_session_names_no_one(no_fallbacks):
    with patch.object(acting_user, "get_current_session", return_value=_session()):
        acting_user.register_acting_user_fallback(lambda: None)
        acting_user.register_acting_user_fallback(lambda: "bob")

        assert acting_user.acting_username() == "bob"


def test_a_failing_fallback_is_skipped(no_fallbacks):
    def failing():
        raise RuntimeError("no script run context")

    with patch.object(acting_user, "get_current_session", return_value=None):
        acting_user.register_acting_user_fallback(failing)

        assert acting_user.acting_username() is None
