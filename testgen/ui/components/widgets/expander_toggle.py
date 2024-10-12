import streamlit as st

from testgen.ui.components.utils.component import component


def expander_toggle(
    default: bool = False,
    expand_label: str | None = None,
    collapse_label: str | None = None,
    key: str = "testgen:expander_toggle",
) -> bool:
    """
    Testgen component to display a toggle for an expandable container.

    # Parameters
    :param default: default state for the component, default=False (collapsed)
    :param expand_label: label for collapsed state, default="Expand"
    :param collapse_label: label for expanded state, default="Collapse"
    :param key: unique key to give the component a persisting state
    """

    if key in st.session_state:
        default = st.session_state[key]

    return component(
        id_="expander_toggle",
        key=key,
        default=default,
        props={"default": default, "expandLabel": expand_label, "collapseLabel": collapse_label},
    )
