import typing

from testgen.ui.components.utils.component import component
from testgen.ui.navigation.router import Router
from testgen.ui.session import session

TooltipPosition = typing.Literal["left", "right"]


def link(
    href: str,
    label: str,
    *,
    params: dict = {},  # noqa: B006
    open_new: bool = False,
    underline: bool = True,
    left_icon: str | None = None,
    left_icon_size: float = 20.0,
    right_icon: str | None = None,
    right_icon_size: float = 20.0,
    height: float | None = 21.0,
    width: float | None = None,
    style: str | None = None,
    disabled: bool = False,
    tooltip: str | None = None,
    tooltip_position: TooltipPosition = "left",
    key: str = "testgen:link",
) -> None:
    props = {
        "href": href,
        "params": params,
        "label": label,
        "height": height,
        "open_new": open_new,
        "underline": underline,
        "disabled": disabled,
    }
    if left_icon:
        props.update({"left_icon": left_icon, "left_icon_size": left_icon_size})

    if right_icon:
        props.update({"right_icon": right_icon, "right_icon_size": right_icon_size})

    if style:
        props.update({"style": style})

    if width:
        props.update({"width": width})

    if tooltip:
        props.update({"tooltip": tooltip, "tooltipPosition": tooltip_position})

    clicked = component(id_="link", key=key, props=props)
    if clicked:
        # Prevent handling the same event multiple times
        event_id = clicked.get("_id")
        if event_id != session.link_event_id:
            session.link_event_id = event_id
            Router().navigate(to=href, with_args=params)
