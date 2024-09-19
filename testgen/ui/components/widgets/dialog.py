import functools
import random
import string
import typing

import streamlit as st
from streamlit.elements.lib.dialog import DialogWidth


def dialog(title: str, *, width: DialogWidth = "small", key: str | None = None) -> typing.Callable:
    """
    Wrap Streamlit's native dialog to avoid passing parameters that will
    be ignored during the fragment's re-run.
    """
    dialog_contents: typing.Callable = lambda: None

    def render_dialog() -> typing.Any:
        args = []
        kwargs = {}
        if key:
            args, kwargs = st.session_state[key]
        return dialog_contents(*args, **kwargs)

    name_suffix = "".join(random.choices(string.ascii_lowercase, k=8))  # noqa: S311

    # NOTE: st.dialog uses __qualname__ to generate the fragment hash, effectively overshadowing the uniqueness of the
    # render_dialog() function.
    render_dialog.__name__ = f"render_dialog_{name_suffix}"
    render_dialog.__qualname__ = render_dialog.__qualname__.replace("render_dialog", render_dialog.__name__)

    render_dialog = st.dialog(title=title, width=width)(render_dialog)

    def decorator(func: typing.Callable) -> typing.Callable:
        nonlocal dialog_contents
        dialog_contents = func

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if key:
                st.session_state[key] = (args, kwargs)
            render_dialog()
        return wrapper

    return decorator
