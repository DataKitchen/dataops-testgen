import contextlib
import dataclasses
import typing

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

CARD_CLASS: str = "testgen_card"
CARD_HEADER_CLASS: str = "testgen_card-header"
CARD_TITLE_CLASS: str = "testgen_card-title"
CARD_SUBTITLE_CLASS: str = "testgen_card-subtitle"
CARD_ACTIONS_CLASS: str = "testgen_card-actions"


@contextlib.contextmanager
def card(
    title: str = "",
    subtitle: str = "",
    border: bool = True,
    extra_css_class: str = "",
) -> typing.Generator["CardContext", None, None]:
    with st.container(border=border):
        st.html(f'<i class="bg-white {CARD_CLASS} {extra_css_class}"></i>')

        title_column, actions_column = st.columns([.5, .5], vertical_alignment="center")
        if title or subtitle:
            with title_column:
                header_html: str = f'<div class="{CARD_HEADER_CLASS}">'
                if title:
                    header_html += f'<h4 class="{CARD_TITLE_CLASS}">{title}</h4>'
                if subtitle:
                    header_html += f'<small class="{CARD_SUBTITLE_CLASS}">{subtitle}</small>'
                header_html += "</div>"
                st.html(header_html)

        actions_column.html(f'<i class="{CARD_ACTIONS_CLASS} flex-row flex-end"></i>')

        yield CardContext(actions=actions_column)


@dataclasses.dataclass
class CardContext:
    actions: DeltaGenerator
