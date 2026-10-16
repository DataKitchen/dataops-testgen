from unittest.mock import MagicMock, patch

import pytest

from testgen.ui.auth import Authentication

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.auth"


@pytest.fixture
def ui_session():
    with (
        patch(f"{MODULE}.session") as session,
        patch(f"{MODULE}.execute_javascript"),
        patch(f"{MODULE}.MixpanelService"),
    ):
        session.sidebar_project = None
        yield session


@patch(f"{MODULE}.get_user")
def test_login_user_records_the_sign_in(mock_get_user, ui_session, audit_log):
    mock_get_user.return_value = MagicMock()
    auth = Authentication()

    auth.login_user("alice")

    mock_get_user.return_value.save.assert_called_once_with(update_latest_login=True)
    [entry] = audit_log.records()
    assert (entry["action"], entry["outcome"]) == ("user.signed_in", "succeeded")


def test_sign_out_records_and_ends_the_session(ui_session, audit_log):
    auth = Authentication()
    auth.user = MagicMock()

    auth.sign_out()

    assert auth.user is None
    assert auth.logging_out is True
    assert ui_session.authentication_status is None
    [entry] = audit_log.records()
    assert entry["action"] == "user.signed_out"


def test_sign_out_without_a_user_records_nothing(ui_session, audit_log):
    auth = Authentication()

    auth.sign_out()

    assert audit_log.records() == []
