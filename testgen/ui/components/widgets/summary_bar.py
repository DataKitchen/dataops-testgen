import logging
import typing

from testgen.ui.components.utils.component import component

LOG = logging.getLogger("testgen")


def summary_bar(
    items: list["SummaryItem"],
    height: int | None = None,
    width: int | None = None,
    key: str = "testgen:summary_bar",
) -> None:
    """
    Testgen component to display a summary status bar.

    # Parameters
    :param items: list of dicts with value, label, and color
    :param height: height of bar in pixels, default=24
    :param width: width of bar in pixels, default is 100% of parent
    :param key: unique key to give the component a persisting state
    """

    component(
        id_="summary_bar",
        key=key,
        default={},
        props={"items": items, "height": height, "width": width},
    )


class SummaryItem(typing.TypedDict):
    value: int
    label: str
    color: str
