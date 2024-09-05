from collections.abc import Iterable

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from testgen.ui.components.utils.component import component


def sorting_selector(
    columns: Iterable[tuple[str, str]],
    default: Iterable[tuple[str, str]] = (),
    popover_label: str = "Sort",
    key: str = "testgen:sorting_selector",
) -> list[tuple[str, str]]:
    """
    Renders a pop over that, when clicked, shows a list of database columns to be selected for sorting.

    # Parameters
    :param columns: Iterable of 2-tuples, being: (<column label>, <database column reference>)
    :param default: Iterable of 2-tuples, being: (<database column reference>, <direction: ASC|DESC>)
    :param key: unique key to give the component a persisting state

    # Return value
    Returns a list of 2-tuples, being: (<database column reference>, <direction: ASC|DESC>)
    """

    ctx = get_script_run_ctx()
    try:
        state = ctx.session_state[key]
    except KeyError:
        state = default

    with st.popover(popover_label):
        return component(
            id_="sorting_selector",
            key=key,
            default=default,
            props={"columns": columns, "state": state},
        )
