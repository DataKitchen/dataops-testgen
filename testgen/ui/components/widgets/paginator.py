import math
import typing

import streamlit as st

from testgen.ui.components.utils.component import component
from testgen.ui.navigation.router import Router


def paginator(
    count: int,
    page_size: int,
    page_index: int | None = None,
    bind_to_query: str | None = None,
    on_change: typing.Callable | None = None,
    key: str = "testgen:paginator",
) -> bool:
    """
    Testgen component to display pagination arrows.

    # Parameters
    :param count: total number of items being paginated
    :param page_size: number of items displayed per page
    :param page_index: index of initial page displayed, default=0 (first page)
    :param key: unique key to give the component a persisting state
    """

    def on_page_change():
        if bind_to_query:
            if event_data := st.session_state[key]:
                Router().set_query_params({ bind_to_query: event_data.get("page_index", 0) })
        if on_change:
            on_change()

    if page_index is None:
        bound_value = st.query_params.get(bind_to_query, "")
        page_index = int(bound_value) if bound_value.isdigit() else 0
        page_index = page_index if page_index < math.ceil(count / page_size) else 0

    event_data = component(
        id_="paginator",
        key=key,
        default={ page_index: page_index },
        props={"count": count, "pageSize": page_size, "pageIndex": page_index},
        on_change=on_page_change,
    )
    return event_data.get("page_index", 0)
