import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from testgen.ui.components.widgets.breadcrumbs import Breadcrumb
from testgen.ui.components.widgets.breadcrumbs import breadcrumbs as tg_breadcrumbs

BASE_HELP_URL = "https://docs.datakitchen.io/articles/#!dataops-testgen-help/"
DEFAULT_HELP_TOPIC = "dataops-testgen-help"
SLACK_URL = "https://data-observability-slack.datakitchen.io/join"
TRAINING_URL = "https://info.datakitchen.io/data-quality-training-and-certifications"

def page_header(
    title: str,
    help_topic: str | None = None,
    breadcrumbs: list["Breadcrumb"] | None = None,
):
    with st.container():
        no_flex_gap()
        title_column, links_column = st.columns([0.95, 0.05], vertical_alignment="bottom")

        with title_column:
            no_flex_gap()
            st.html(f'<h3 class="tg-header">{title}</h3>')
            if breadcrumbs:
                tg_breadcrumbs(breadcrumbs=breadcrumbs)

        with links_column:
            page_links(help_topic)

        st.html('<hr size="3" class="tg-header--line">')


def page_links(help_topic: str | None = None):
    css_class("tg-header--links")
    flex_row_end()
    st.link_button(":material/question_mark:", f"{BASE_HELP_URL}{help_topic or DEFAULT_HELP_TOPIC}", help="Help Center")
    st.link_button(":material/group:", SLACK_URL, help="Slack Community")
    st.link_button(":material/school:", TRAINING_URL, help="Training Portal")


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


def flex_row_center(container: DeltaGenerator | None = None):
    _apply_html('<i class="flex-row flex-center"></i>', container)


def no_flex_gap(container: DeltaGenerator | None = None):
    _apply_html('<i class="no-flex-gap"></i>', container)


def _apply_html(html: str, container: DeltaGenerator | None = None):
    if container:
        container.html(html)
    else:
        st.html(html)
