import pathlib
from collections.abc import Callable

import streamlit as st
from streamlit.components import v1 as components
from streamlit.components.v2.bidi_component.state import BidiComponentResult
from streamlit.components.v2.types import ComponentRenderer

components_dir = pathlib.Path(__file__).parent.parent.joinpath("frontend")
component_function = components.declare_component("testgen", path=components_dir)


def component(*, id_, props, key=None, default=None, on_change=None):
    component_props = props
    if not component_props:
        component_props = {}
    return component_function(id=id_, props=component_props, key=key, default=default, on_change=on_change)


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

        return renderer(**other_kwargs, **on_change_callbacks)
    return wrapped_renderer


def _is_change_callback(name: str) -> bool:
    return name.startswith("on_") and name.endswith("_change")


def _wrap_handler(key: str | None, callback_name: str | None, callback: Callable | None):
    if key and callback_name and callback:
        def wrapper():
            component_value = st.session_state[key] or {}
            trigger_value_name = callback_name.removeprefix("on_").removesuffix("_change")
            trigger_value = (component_value.get(trigger_value_name) or {}).get("payload")
            return callback(trigger_value)
        return wrapper
    return callback
