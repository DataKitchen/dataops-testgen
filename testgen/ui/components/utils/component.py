from collections.abc import Callable

import streamlit as st
from streamlit.components.v2.bidi_component.state import BidiComponentResult
from streamlit.components.v2.types import ComponentRenderer


def component_v2_wrapped(renderer: ComponentRenderer) -> ComponentRenderer:
    def wrapped_renderer(key: str | None = None, **kwargs) -> BidiComponentResult:
        on_change_callbacks = {
            name: fn for name, fn, in kwargs.items()
            if _is_change_callback(name)
        }
        other_kwargs = {
            "key": key,
            **{
                name: value for name, value, in kwargs.items()
                if not _is_change_callback(name) and name != "key"
            }
        }
        for name, callback in on_change_callbacks.items():
            on_change_callbacks[name] = _wrap_handler(key, name, callback)

        # Auto-handle LinkClicked events (navigation) if not explicitly overridden
        if "on_LinkClicked_change" not in on_change_callbacks:
            on_change_callbacks["on_LinkClicked_change"] = _link_clicked_handler(key)

        return renderer(**other_kwargs, **on_change_callbacks)
    return wrapped_renderer


def _is_change_callback(name: str) -> bool:
    return name.startswith("on_") and name.endswith("_change")


def _link_clicked_handler(key: str | None):
    """Auto-handles LinkClicked events emitted by Link components in v2 pages."""
    from testgen.ui.navigation.router import Router

    def handler():
        component_value = st.session_state.get(key) or {}
        link_data = component_value.get("LinkClicked") or {}
        href = link_data.get("href")
        params = link_data.get("params")
        if href:
            Router().queue_navigation(to=href, with_args=params)
    return handler


def _wrap_handler(key: str | None, callback_name: str | None, callback: Callable | None):
    if key and callback_name and callback:
        def wrapper():
            component_value = st.session_state.get(key) or {}
            trigger_value_name = callback_name.removeprefix("on_").removesuffix("_change")
            trigger_value = (component_value.get(trigger_value_name) or {}).get("payload")
            return callback(trigger_value)
        return wrapper
    return callback
