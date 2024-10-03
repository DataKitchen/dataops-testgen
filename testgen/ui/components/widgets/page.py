import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from testgen.ui.components.widgets.breadcrumbs import Breadcrumb
from testgen.ui.components.widgets.breadcrumbs import breadcrumbs as tg_breadcrumbs


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
