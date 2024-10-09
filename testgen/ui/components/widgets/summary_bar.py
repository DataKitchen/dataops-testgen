import typing

import streamlit as st

COLOR_MAP = {
    "red": "#EF5350",
    "orange": "#FF9800",
    "yellow": "#FDD835",
    "green": "#9CCC65",
    "purple": "#AB47BC",
    "blue": "#42A5F5",
    "brown": "#8D6E63",
    "grey": "#BDBDBD",
}

def summary_bar(
    items: list["SummaryItem"],
    label: str | None = None,
    height: int = 24,
    width: int | None = None,
) -> None:
    """
    Testgen component to display a summary status bar.

    # Parameters
    :param items: list of dicts with value, label, and color
    :param height: height of bar in pixels, default=24
    :param width: width of bar in pixels, default is 100% of parent
    :param key: unique key to give the component a persisting state
    """

    label_div = ""
    item_spans = ""
    caption_div = ""

    if label:
        label_div = f"""
        <div class="tg-summary-bar--label">
        {label}
        </div>
        """

    total = sum(item["value"] for item in items)
    if total:
        item_spans = "".join([ f'<span class="tg-summary-bar--item" style="width: {item["value"] * 100 / total}%; background-color: {COLOR_MAP.get(item["color"], item["color"])};"></span>' for item in items ])

        caption = ", ".join([ f"{item['label']}: {item['value']}" for item in items ])
        caption_div = f"""
        <div class="tg-summary-bar--caption">
            {caption}
        </div>
        """

    st.html(f"""
            <div class="tg-summary-bar-wrapper">
                {label_div}
                <div class="tg-summary-bar" style="height: {height}px; max-width: {f'{width}px' if width else '100%'};">
                    {item_spans}
                </div>
                {caption_div}
            </div>
            """)


class SummaryItem(typing.TypedDict):
    value: int
    label: str
    color: str
