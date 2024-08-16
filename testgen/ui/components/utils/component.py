import pathlib

from streamlit.components import v1 as components

components_dir = pathlib.Path(__file__).parent.parent.joinpath("frontend")
component_function = components.declare_component("testgen", path=components_dir)


def component(*, id_, props, key=None, default=None, on_change=None):
    component_props = props
    if not component_props:
        component_props = {}
    return component_function(id=id_, props=component_props, key=key, default=default, on_change=on_change)
