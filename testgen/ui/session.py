from collections.abc import Callable
from typing import Any, Literal, TypeVar

import streamlit as st
from streamlit.runtime.state import SessionStateProxy

from testgen.utils.singleton import Singleton

T = TypeVar("T")
TempValueGetter = Callable[..., T]
TempValueSetter = Callable[[T], None]


class TestgenSession(Singleton):
    cookies_ready: int
    logging_in: bool
    logging_out: bool
    page_pending_cookies: st.Page  # type: ignore
    page_pending_login: str
    page_pending_sidebar: str
    page_args_pending_router: dict

    current_page: str
    current_page_args: dict

    dbschema: str

    name: str
    username: str
    authentication_status: bool
    auth_role: Literal["admin", "data_quality", "analyst", "business", "catalog"]
    user_default_page: str

    project: str
    add_project: bool
    latest_version: str | None

    testgen_event_id: str | None

    def __init__(self, state: SessionStateProxy) -> None:
        super().__setattr__("_state", state)

    def __getattr__(self, key: str) -> Any:
        state = object.__getattribute__(self, "_state")
        if key not in state:
            return None
        return state[key]

    def __setattr__(self, key: str, value: Any) -> None:
        object.__getattribute__(self, "_state")[key] = value

    def __delattr__(self, key: str) -> None:
        state = object.__getattribute__(self, "_state")
        if key in state:
            del state[key]


def temp_value(session_key: str, *, default: T | None = None) -> tuple[TempValueGetter[T | None], TempValueSetter[T]]:
    scoped_session_key = f"tg-session:tmp-value:{session_key}"

    def getter() -> T | None:
        if scoped_session_key not in st.session_state:
            return default
        return st.session_state.pop(scoped_session_key, None)

    def setter(value: T):
        st.session_state[scoped_session_key] = value

    return getter, setter

session: TestgenSession = TestgenSession(st.session_state)
