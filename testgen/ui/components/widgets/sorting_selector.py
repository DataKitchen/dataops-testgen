import itertools
import re
from collections.abc import Callable, Iterable
from typing import Any

import streamlit as st

from testgen.ui.components.utils.component import component
from testgen.ui.navigation.router import Router


def _slugfy(text) -> str:
    return re.sub(r"[^a-z]+", "-", text.lower())


def _state_to_str(columns, state):
    state_parts = []
    state_dict = dict(state)
    try:
        for col_label, col_id in columns:
            if col_id in state_dict:
                state_parts.append(".".join((_slugfy(col_label), state_dict[col_id].lower())))
        return "-".join(state_parts) or "-"
    except Exception:
        return None


def _state_from_str(columns, state_str):
    col_slug_to_id = {_slugfy(col_label): col_id for col_label, col_id in columns}
    state_part_re = re.compile("".join(("(", "|".join(col_slug_to_id.keys()), r")\.(asc|desc)")))
    state = [
        [col_slug_to_id[col_slug], direction.upper()]
        for col_slug, direction
        in state_part_re.findall(state_str)
    ]
    return state


def sorting_selector(
    columns: Iterable[tuple[str, str]],
    default: Iterable[tuple[str, str]] = (),
    on_change: Callable[[], Any] | None = None,
    popover_label: str = "Sort",
    query_param: str | None = "sort",
    key: str = "testgen:sorting_selector",
) -> list[tuple[str, str]]:
    """
    Renders a pop over that, when clicked, shows a list of database columns to be selected for sorting.

    # Parameters
    :param columns: Iterable of 2-tuples, being: (<column label>, <database column reference>)
    :param default: Iterable of 2-tuples, being: (<database column reference>, <direction: ASC|DESC>)
    :param on_change: Callable that will be called when the component state is updated
    :param popover_label: Label to be applied to the pop-over button. Default: 'Sort'
    :param query_param: Name of the query parameter that will store the component state. Can be disabled by setting
                        to None. Default: 'sort'.
    :param key: unique key to give the component a persisting state

    # Return value
    Returns a list of 2-tuples, being: (<database column reference>, <direction: ASC|DESC>)
    """

    state = None

    try:
        state = st.session_state[key]
    except KeyError:
        pass

    if state is None and query_param and (state_str := st.query_params.get(query_param)):
        state = _state_from_str(columns, state_str)

    if state is None:
        state = default

    with st.popover(popover_label):
        new_state = component(
            id_="sorting_selector",
            key=key,
            default=state,
            on_change=on_change,
            props={"columns": columns, "state": state},
        )

    # For some unknown reason, sometimes, streamlit returns None as the component state
    new_state = [] if new_state is None else new_state

    if query_param:
        if tuple(itertools.chain(*default)) == tuple(itertools.chain(*new_state)):
            value = None
        else:
            value = _state_to_str(columns, new_state)
        Router().set_query_params({query_param: value})

    return new_state
