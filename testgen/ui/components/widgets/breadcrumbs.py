import typing

from testgen.ui.components.utils.component import component
from testgen.ui.navigation.router import Router
from testgen.ui.session import session


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

    data = component(
        id_="breadcrumbs",
        key=key,
        props={"breadcrumbs": breadcrumbs},
    )
    if data:
        # Prevent handling the same event multiple times
        event_id = data.get("_id")
        if event_id != session.breadcrumb_event_id:
            session.breadcrumb_event_id = event_id
            Router().navigate(to=data["href"], with_args=data["params"])

class Breadcrumb(typing.TypedDict):
    path: str | None
    params: dict
    label: str
