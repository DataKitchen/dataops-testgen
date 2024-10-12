# ruff: noqa: S105

import logging
import typing

import streamlit as st

from testgen.common.encrypt import encrypt_ui_password
from testgen.ui.queries import authentication_queries
from testgen.ui.session import session

RoleType = typing.Literal["admin", "edit", "read"]

LOG = logging.getLogger("testgen")


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
