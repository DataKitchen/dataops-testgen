import base64
import dataclasses
import logging
import typing

import streamlit as st

from testgen.ui.components.utils.callbacks import register_callback
from testgen.ui.components.utils.component import component
from testgen.ui.session import session

LOG = logging.getLogger("testgen")


def location(
    key: str = "testgen:location",
    on_change: typing.Callable[["LocationChanged"], None] | None = None,
) -> None:
    """
    Testgen component to listen for location changes in the url hash.

    # Parameters
    :param key: unique key to give the component a persisting state
    :param on_change: callback for when the browser location changes
    """
    register_callback(key, _handle_location_change, key, on_change)

    initialized = bool(session.renders and session.renders > 1)
    current_page_code = _encode_page(session.current_page, session.current_page_args or {})

    change = component(
        id_="location",
        key=key,
        default={},
        props={"initialized": initialized, "current_page_code": current_page_code},
    )

    if not initialized and change:
        change = LocationChanged(**change)
        if _encode_page(change.page, change.args) != current_page_code:
            _handle_location_change(key, on_change)


def _handle_location_change(key: str, callback: typing.Callable[["LocationChanged"], None] | None):
    if callback:
        change = st.session_state[key]
        if "page" not in change:
            change["page"] = "overview"
        return callback(LocationChanged(**change))


def _encode_page(page: str, args: dict) -> str | None:
    page_code = None
    if page:
        query_params = "&".join([f"{name}={value}" for name, value in args.items()])
        if query_params:
            page = f"{page}?{query_params}"
        page_code = base64.b64encode(page.encode()).decode()
    return page_code


@dataclasses.dataclass
class LocationChanged:
    page: str
    args: dict = dataclasses.field(default_factory=dict)
