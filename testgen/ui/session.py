import typing

from streamlit import session_state
from streamlit.runtime.state import SessionStateProxy

from testgen.utils.singleton import Singleton


class TestgenSession(Singleton):
    renders: int
    current_page: str
    current_page_args: dict

    dbschema: str

    name: str
    username: str
    authentication_status: bool
    auth_role: typing.Literal["admin", "edit", "read"]
    logging_out: bool

    project: str
    add_project: bool

    sb_latest_rel: str
    sb_schema_rev: str

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


session = TestgenSession(session_state)
