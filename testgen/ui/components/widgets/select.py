import pandas as pd
import streamlit as st
from streamlit_extras.no_default_selectbox import selectbox

from testgen.ui.navigation.router import Router

EMPTY_VALUE = "---"

def select(
    label: str,
    options: pd.DataFrame | list[str],
    value_column: str | None = None,
    display_column: str | None = None,
    default_value = None,
    required: bool = False,
    bind_to_query: str | None = None,
    bind_empty_value: bool = False,
    **kwargs,
):
    kwargs = {**kwargs}
    kwargs["label"] = label

    if isinstance(options, pd.DataFrame):
        value_column = value_column or options.columns[0]
        display_column = display_column or value_column
        kwargs["options"] = options[display_column]
        if default_value in options[value_column].values:
            kwargs["index"] = int(options[options[value_column] == default_value].index[0]) + (0 if required else 1)
    else:
        kwargs["options"] = options
        if default_value in options:
            kwargs["index"] = options.index(default_value) + (0 if required else 1)
        elif default_value == EMPTY_VALUE and not required: 
            kwargs["index"] = 0

    if bind_to_query:
        kwargs["key"] = kwargs.get("key", f"testgen_select_{bind_to_query}")
        if default_value is not None and kwargs.get("index") is None:
            Router().set_query_params({ bind_to_query: None }) # Unset the query params if the current value is not valid

        def update_query_params():
            query_value = st.session_state[kwargs["key"]]
            if not required and query_value == EMPTY_VALUE and not bind_empty_value:
                query_value = None
            elif isinstance(options, pd.DataFrame):
                query_value = options.loc[options[display_column] == query_value, value_column].iloc[0]
            Router().set_query_params({ bind_to_query: query_value })

        kwargs["on_change"] = update_query_params

    selected = st.selectbox(**kwargs) if required else selectbox(**kwargs)

    if selected and isinstance(options, pd.DataFrame):
        return options.loc[options[display_column] == selected, value_column].iloc[0]

    return selected
