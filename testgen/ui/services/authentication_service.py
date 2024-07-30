# ruff: noqa: S105

import datetime
import logging
import typing

import extra_streamlit_components as stx
import jwt
import streamlit as st

from testgen.common.encrypt import encrypt_ui_password
from testgen.ui.queries import authentication_queries
from testgen.ui.session import session

RoleType = typing.Literal["admin", "edit", "read"]

JWT_HASHING_KEY = "dk_signature_key"
AUTH_TOKEN_COOKIE_NAME = "dk_cookie_name"
AUTH_TOKEN_EXPIRATION_DAYS = 5

LOG = logging.getLogger("testgen")


def load_user_session() -> None:
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
    session.auth_role = get_role_for_user(get_auth_data(), username)
    session.authentication_status = True
    if not session.current_page or session.current_page == "login":
        session.current_page = "overview"
        session.current_page_args = {}
    session.logging_out = False


def end_user_session() -> None:
    session.auth_role = None
    session.authentication_status = None
    session.current_page = "login"
    session.current_page_args = {}
    session.logging_out = True

    del session.name
    del session.username


def add_user(user):
    encrypted_password = encrypt_ui_password(user["password"])
    schema = st.session_state["dbschema"]
    authentication_queries.add_user(schema, user, encrypted_password)


def delete_users(user_ids):
    schema = st.session_state["dbschema"]
    return authentication_queries.delete_users(schema, user_ids)


def edit_user(user):
    encrypted_password = encrypt_ui_password(user["password"])
    schema = st.session_state["dbschema"]
    authentication_queries.edit_user(schema, user, encrypted_password)


def get_auth_data():
    auth_data = authentication_queries.get_users(session.dbschema)

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


def get_users():
    return authentication_queries.get_users(session.dbschema)


def get_role_for_user(auth_data, username):
    return auth_data["credentials"]["usernames"][username]["role"]


def current_user_has_admin_role():
    return session.auth_role == "admin"


def current_user_has_edit_role():
    return session.auth_role in ("edit", "admin")


def current_user_has_read_role():
    return not session.auth_role or session.auth_role == "read"


def current_user_has_role(role: RoleType) -> bool:
    return session.auth_role == role
