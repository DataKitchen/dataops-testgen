import pandas
import streamlit as st
from reportlab.lib import enums
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import TableStyle

from testgen.common import date_service

COLOR_GRAY_BG = HexColor(0xF2F2F2)
COLOR_GREEN_BG = HexColor(0xDCE4DA)
COLOR_YELLOW_BG = HexColor(0xA0C84E40, hasAlpha=True)
COLOR_GREEN_TEXT = HexColor(0x139549)
COLOR_FADED_TEXT = HexColor(0x404040)
COLOR_LINK_TEXT = HexColor(0x1976D2)

PARA_STYLE_DEFAULT = ParagraphStyle(
    "default",
    fontSize=8,
    fontName="Helvetica",
)

PARA_STYLE_TEXT = ParagraphStyle(
    "text",
    PARA_STYLE_DEFAULT,
    fontName="Times-Roman",
)

PARA_STYLE_INFO = ParagraphStyle(
    "info",
    PARA_STYLE_DEFAULT,
    fontName="Helvetica",
    backColor=COLOR_YELLOW_BG,
    borderPadding=12,
    leftIndent=12,
    rightIndent=12,
    spaceBefore=18,
    spaceAfter=18,
)

PARA_STYLE_MONO = ParagraphStyle(
    "monospaced",
    PARA_STYLE_DEFAULT,
    fontName="Courier",
    borderPadding=4,
    backColor=COLOR_GRAY_BG,
    leftIndent=4,
    rightIndent=4,
    spaceBefore=8,
    spaceAfter=8,
)

PARA_STYLE_FOOTNOTE = ParagraphStyle(
    "footnote",
    PARA_STYLE_DEFAULT,
    fontSize=6,
    fontName="Helvetica-Oblique",
    textColor=COLOR_FADED_TEXT,
)

PARA_STYLE_TITLE = ParagraphStyle(
    "title",
    PARA_STYLE_DEFAULT,
    fontSize=18,
    leading=30,
    alignment=enums.TA_CENTER,
    spaceBefore=12,
    spaceAfter=4,
    textColor=COLOR_GREEN_TEXT,
)

PARA_STYLE_H1 = ParagraphStyle(
    "heading_1",
    PARA_STYLE_TITLE,
    fontSize=12,
    leading=16,
    alignment=enums.TA_LEFT,
)

TABLE_STYLE_DEFAULT = TableStyle(
    (
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONT", (0, 0), (-1, -1), "Helvetica", 7),
    )
)

PARA_STYLE_CELL = ParagraphStyle(
    "table_cell",
    fontSize=7,
    fontName="Helvetica",
    leading=10,
)

PARA_STYLE_LINK = ParagraphStyle(
    "link",
    PARA_STYLE_DEFAULT,
    fontSize=9,
    alignment=enums.TA_RIGHT,
    textColor=COLOR_LINK_TEXT,
)


def get_formatted_datetime(value) -> str:
    return date_service.get_timezoned_timestamp(
        st.session_state,
        pandas.to_datetime(value),
        "%b %-d, %-I:%M %p %Z",
    )
