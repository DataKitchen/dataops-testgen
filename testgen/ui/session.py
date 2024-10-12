import typing

import streamlit as st
from streamlit.runtime.state import SessionStateProxy

from testgen.utils.singleton import Singleton


class TestgenSession(Singleton):
    cookies_ready: bool
    logging_in: bool
    logging_out: bool
    page_pending_cookies: st.Page
    page_pending_login: str
    page_pending_sidebar: str
    page_args_pending_router: dict
    
    current_page: str
    current_page_args: dict

    dbschema: str

    name: str
    username: str
    authentication_status: bool
    auth_role: typing.Literal["admin", "edit", "read"]

    project: str
    add_project: bool
    latest_version: str | None

    def __init__(self, state: SessionStateProxy) -> None:
        super().__setattr__("_state", state)

    def __getattr__(self, key: str) -> typing.Any:
        state = object.__getattribute__(self, "_state")
        if key not in state:
            return None
        return state[key]

    def __setattr__(self, key: str, value: typing.Any) -> None:
        object.__getattribute__(self, "_state")[key] = value

    def __delattr__(self, key: str) -> None:
        state = object.__getattribute__(self, "_state")
        if key in state:
            del state[key]


session: TestgenSession = TestgenSession(st.session_state)
