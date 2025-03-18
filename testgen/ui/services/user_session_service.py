import datetime
import logging
import typing

import extra_streamlit_components as stx
import jwt
import streamlit as st

from testgen.ui.queries import user_queries
from testgen.ui.session import session

RoleType = typing.Literal["admin", "data_quality", "analyst", "business", "catalog"]

JWT_HASHING_KEY = "dk_signature_key"
AUTH_TOKEN_COOKIE_NAME = "dk_cookie_name"  # noqa: S105
AUTH_TOKEN_EXPIRATION_DAYS = 1
DISABLED_ACTION_TEXT = "You do not have permissions to perform this action. Contact your administrator."

LOG = logging.getLogger("testgen")


def load_user_session() -> None:
    # Replacing this with st.context.cookies does not work
    # Because it does not update when cookies are deleted on logout
    cookies = stx.CookieManager(key="testgen.cookies.get")
    token = cookies.get(AUTH_TOKEN_COOKIE_NAME)
    if token is not None:
        try:
            token = jwt.decode(token, JWT_HASHING_KEY, algorithms=["HS256"])
            if token["exp_date"] > datetime.datetime.utcnow().timestamp():
                start_user_session(token["name"], token["username"])
        except Exception:
            LOG.debug("Invalid auth token found on cookies", exc_info=True, stack_info=True)


def start_user_session(name: str, username: str) -> None:
    session.name = name
    session.username = username
    session.auth_role = get_auth_data()["credentials"]["usernames"][username]["role"]
    session.authentication_status = True
    session.logging_out = False
    if user_has_catalog_role():
        session.user_default_page = "data-catalog"
        st.rerun()
    else:
        session.user_default_page = "project-dashboard"


def end_user_session() -> None:
    session.auth_role = None
    session.authentication_status = None
    session.logging_out = True
    session.user_default_page = ""

    del session.name
    del session.username


def get_auth_data():
    auth_data = user_queries.get_users()

    usernames = {}
    preauthorized_list = []

    for item in auth_data.itertuples():
        usernames[item.username] = {
            "email": item.email,
            "name": item.name,
            "password": item.password,
            "role": item.role,
        }
        if item.preauthorized:
            preauthorized_list.append(item.email)

    return {
        "credentials": {"usernames": usernames},
        "cookie": {"expiry_days": AUTH_TOKEN_EXPIRATION_DAYS, "key": JWT_HASHING_KEY, "name": AUTH_TOKEN_COOKIE_NAME},
        "preauthorized": {"emails": preauthorized_list},
    }


def user_is_admin():
    return session.auth_role == "admin"


def user_can_edit():
    return session.auth_role in ("admin", "data_quality")


def user_can_disposition():
    return session.auth_role in ("admin", "data_quality", "analyst")


def user_has_catalog_role():
    return session.auth_role == "catalog"


def user_has_role(role: RoleType) -> bool:
    return session.auth_role == role
