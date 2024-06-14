import logging
import typing

from testgen.ui.components.utils.component import component

LOG = logging.getLogger("testgen")


def breadcrumbs(
    key: str = "testgen:breadcrumbs",
    breadcrumbs: list["Breadcrumb"] | None = None,
) -> None:
    """
    Testgen component to display the breadcrumbs with a hash link on
    each page.

    # Parameters
    :param key: unique key to give the component a persisting state
    :param breadcrumbs: list of dicts with label and path
    """

    component(
        id_="breadcrumbs",
        key=key,
        default={},
        props={"breadcrumbs": breadcrumbs},
    )


class Breadcrumb(typing.TypedDict):
    path: str | None
    label: str
