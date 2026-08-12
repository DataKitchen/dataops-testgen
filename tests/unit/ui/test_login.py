from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
import streamlit_authenticator as stauth

from testgen.ui.session import TestgenSession
from testgen.ui.views.login import LoginPage

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.views.login"
STAUTH_MODULE = "streamlit_authenticator.authenticate"

COOKIE_NAME = "dk_cookie_name"
SIGNING_KEY = "unit-test-signing-key"
USERNAME = "someone"
PASSWORD = "correct-horse-battery-staple"  # noqa: S105
HASHED_PASSWORD = stauth.Hasher([PASSWORD]).generate()[0]
CREDENTIALS = {"usernames": {USERNAME: {"name": "Someone", "password": HASHED_PASSWORD}}}


def _reauthentication_cookie() -> str:
    return jwt.encode(
        {
            "name": "Someone",
            "username": USERNAME,
            "exp_date": (datetime.now(UTC) + timedelta(days=1)).timestamp(),
        },
        SIGNING_KEY,
        algorithm="HS256",
    )


@contextmanager
def _patched_authenticator(state: dict, cookie: str | None = None, submitted: dict | None = None):
    """Run `streamlit_authenticator` for real, against `state` and a cookie jar holding `cookie`."""
    stauth_st = MagicMock()
    stauth_st.session_state = state
    login_form = stauth_st.form.return_value
    login_form.form_submit_button.return_value = submitted is not None
    login_form.text_input.side_effect = lambda label, **_kwargs: (submitted or {}).get(label, "")

    with (
        patch(f"{STAUTH_MODULE}.st", stauth_st),
        patch(f"{STAUTH_MODULE}.stx.CookieManager") as cookie_manager,
    ):
        cookie_manager.return_value.get.return_value = cookie
        yield


@contextmanager
def _rendered_login_page(cookie: str | None = None, submitted: dict | None = None):
    """Render the login page over a session state shared with the real authenticator."""
    auth = MagicMock()
    auth.get_credentials.return_value = CREDENTIALS
    auth.get_jwt_hashing_key.return_value = SIGNING_KEY
    auth.jwt_cookie_name = COOKIE_NAME
    auth.jwt_cookie_expiry_days = 1

    state: dict = {"auth": auth}
    session = TestgenSession.__new__(TestgenSession)
    object.__setattr__(session, "_state", state)

    with (
        _patched_authenticator(state, cookie=cookie, submitted=submitted),
        patch(f"{MODULE}.st"),
        patch(f"{MODULE}.session", session),
        patch(f"{MODULE}.MixpanelService", MagicMock()),
    ):
        LoginPage.__new__(LoginPage).render_login_form()
        yield state, auth


def test_reauthentication_cookie_does_not_log_the_user_back_in():
    with _rendered_login_page(cookie=_reauthentication_cookie()) as (state, auth):
        assert state.get("authentication_status") is not True
        auth.login_user.assert_not_called()


def test_credentials_still_log_the_user_in():
    submitted = {"Username": USERNAME, "Password": PASSWORD}
    with _rendered_login_page(submitted=submitted) as (state, auth):
        assert state["authentication_status"] is True
        assert state["logout"] is False
        assert auth.logging_in is True
        assert auth.logging_out is False
        auth.login_user.assert_called_once_with(USERNAME)


def test_wrong_credentials_are_rejected():
    submitted = {"Username": USERNAME, "Password": "not-the-password"}
    with _rendered_login_page(submitted=submitted) as (state, auth):
        assert state["authentication_status"] is False
        auth.login_user.assert_not_called()


def test_authenticator_reauthenticates_from_the_cookie_unless_disabled():
    """Guards the assumption behind `LoginPage.render_login_form` disabling the cookie."""
    state: dict = {}
    with _patched_authenticator(state, cookie=_reauthentication_cookie()):
        authenticator = stauth.Authenticate(CREDENTIALS, COOKIE_NAME, SIGNING_KEY, 1)
        assert authenticator.login("Login")[1] is True

        state["authentication_status"] = None
        state["logout"] = True
        assert authenticator.login("Login")[1] is None
