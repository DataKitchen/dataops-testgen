import logging
import typing

from testgen.ui.components.utils.component import component
from testgen.ui.navigation.router import Router

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

    path = component(
        id_="breadcrumbs",
        key=key,
        props={"breadcrumbs": breadcrumbs},
    )
    if path:
        Router().navigate(to=path)

class Breadcrumb(typing.TypedDict):
    path: str | None
    label: str
