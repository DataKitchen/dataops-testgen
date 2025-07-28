import re

import pandas as pd
import streamlit as st
from streamlit_extras.no_default_selectbox import selectbox

from testgen.ui.navigation.router import Router

EMPTY_VALUE = "---"
CUSTOM_VALUE_TEMPLATE = "Custom: {value}"
CUSTOM_VALUE_PATTERN = r"Custom: (.+)"


def select(
    label: str,
    options: pd.DataFrame | list[str],
    value_column: str | None = None,
    display_column: str | None = None,
    default_value = None,
    required: bool = False,
    bind_to_query: str | None = None,
    bind_empty_value: bool = False,
    accept_new_options: bool = False,
    custom_values_wrap: str | None = "%{}%",
    **kwargs,
):
    kwargs = {**kwargs, "accept_new_options": accept_new_options}
    kwargs["label"] = label
    kwargs["index"] = None

    option_values = options
    option_display_labels = options

    if isinstance(options, pd.DataFrame):
        if options.empty:
            option_values = []
            option_display_labels = []
        else:
            value_column = value_column or options.columns[0]
            display_column = display_column or value_column

            option_values = options[value_column].values.tolist()
            option_display_labels = options[display_column].values.tolist()

    kwargs["options"] = [*option_display_labels]
    if default_value in option_values:
        kwargs["index"] = option_values.index(default_value) + (0 if required else 1)
    elif default_value == EMPTY_VALUE and not required:
        kwargs["index"] = 0
    elif default_value and default_value != EMPTY_VALUE and accept_new_options:
        kwargs["options"].append(CUSTOM_VALUE_TEMPLATE.format(value=default_value))
        kwargs["index"] = len(kwargs["options"])

    if bind_to_query:
        kwargs["key"] = kwargs.get("key", f"testgen_select_{bind_to_query}")

        # Unset the query params if the current value is not valid and new options are not allowed
        if default_value is not None and kwargs.get("index") is None and not accept_new_options:
            Router().set_query_params({ bind_to_query: None })

        def update_query_params():
            query_value = st.session_state[kwargs["key"]]
            if not required and query_value == EMPTY_VALUE and not bind_empty_value:
                query_value = None
            elif query_value in option_display_labels:
                query_value = option_values[option_display_labels.index(query_value)]
            # elif isinstance(options, pd.DataFrame) and default_value in options[value_column].values:
            #     query_value = options.loc[options[display_column] == query_value, value_column].iloc[0]
            Router().set_query_params({ bind_to_query: query_value })

        kwargs["on_change"] = update_query_params

    selected = st.selectbox(**kwargs) if required else selectbox(**kwargs)

    if selected:
        if selected in option_display_labels:
            selected = option_values[option_display_labels.index(selected)]

        if accept_new_options and (match := re.match(CUSTOM_VALUE_PATTERN, selected)):
            selected = match.group(1)
            if custom_values_wrap:
                selected = custom_values_wrap.format(selected)

    return selected
