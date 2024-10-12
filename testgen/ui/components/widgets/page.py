import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator
from streamlit_extras.no_default_selectbox import selectbox

from testgen.ui.components.widgets.breadcrumbs import Breadcrumb
from testgen.ui.components.widgets.breadcrumbs import breadcrumbs as tg_breadcrumbs
from testgen.ui.navigation.router import Router


def page_header(
    title: str,
    help_link:str | None = None,
    breadcrumbs: list["Breadcrumb"] | None = None,
):
    hcol1, hcol2 = st.columns([0.95, 0.05])
    hcol1.subheader(title, anchor=False)
    if help_link:
        with hcol2:
            whitespace(0.8)
            st.page_link(help_link, label=" ", icon=":material/help:")

    if breadcrumbs:
        tg_breadcrumbs(breadcrumbs=breadcrumbs)

    st.write(
        '<hr style="background-color: #21c354; margin-top: -8px;'
        ' margin-bottom: 0; height: 3px; border: none; border-radius: 3px;">',
        unsafe_allow_html=True,
    )
    if "last_page" in st.session_state:
        if title != st.session_state["last_page"]:
            st.cache_data.clear()
    st.session_state["last_page"] = title


def toolbar_select(
    options: pd.DataFrame | list[str],
    value_column: str | None = None,
    display_column: str | None = None,
    default_value = None,
    required: bool = False,
    bind_to_query: str | None = None,
    **kwargs,
):
    kwargs = {**kwargs}

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

    if bind_to_query:
        kwargs["key"] = kwargs.get("key", f"toolbar_select_{bind_to_query}")
        if default_value is not None and kwargs.get("index") is None:
            Router().set_query_params({ bind_to_query: None }) # Unset the query params if the current value is not valid

        def update_query_params():
            query_value = st.session_state[kwargs["key"]]
            if not required and query_value == "---":
                query_value = None
            elif isinstance(options, pd.DataFrame):
                query_value = options.loc[options[display_column] == query_value, value_column].iloc[0]
            Router().set_query_params({ bind_to_query: query_value })

        kwargs["on_change"] = update_query_params

    selected = st.selectbox(**kwargs) if required else selectbox(**kwargs)

    if selected and isinstance(options, pd.DataFrame):
        return options.loc[options[display_column] == selected, value_column].iloc[0]

    return selected


def whitespace(size: float, container: DeltaGenerator | None = None):
    _apply_html(f'<div style="height: {size}rem"></div>', container)


def divider(margin_top: int = 0, margin_bottom: int = 0, container: DeltaGenerator | None = None):
    _apply_html(f'<hr style="margin: {margin_top}px 0 {margin_bottom}px;">', container)


def text(text: str, styles: str = "", container: DeltaGenerator | None = None):
    _apply_html(f'<p class="text" style="{styles}">{text}</p>', container)


def caption(text: str, styles: str = "", container: DeltaGenerator | None = None):
    _apply_html(f'<p class="caption" style="{styles}">{text}</p>', container)


def css_class(css_classes: str, container: DeltaGenerator | None = None):
    _apply_html(f'<i class="{css_classes}"></i>', container)


def flex_row_start(container: DeltaGenerator | None = None):
    _apply_html('<i class="flex-row flex-start"></i>', container)


def flex_row_end(container: DeltaGenerator | None = None):
    _apply_html('<i class="flex-row flex-end"></i>', container)


def no_flex_gap(container: DeltaGenerator | None = None):
    _apply_html('<i class="no-flex-gap"></i>', container)


def _apply_html(html: str, container: DeltaGenerator | None = None):
    if container:
        container.html(html)
    else:
        st.html(html)
