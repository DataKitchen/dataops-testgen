from testgen.ui.components.utils.component import component
from testgen.ui.navigation.router import Router


def link(
    href: str,
    label: str,
    *,
    params: dict = {},  # noqa: B006
    underline: bool = True,
    left_icon: str | None = None,
    left_icon_size: float = 20.0,
    right_icon: str | None = None,
    right_icon_size: float = 20.0,
    height: float | None = 21.0,
    style: str | None = None,
    key: str = "testgen:link",
) -> None:
    props = {
        "href": href,
        "params": params,
        "label": label,
        "height": height,
        "underline": underline,
    }
    if left_icon:
        props.update({"left_icon": left_icon, "left_icon_size": left_icon_size})

    if right_icon:
        props.update({"right_icon": right_icon, "right_icon_size": right_icon_size})

    if style:
        props.update({"style": style})

    clicked = component(id_="link", key=key, props=props)
    if clicked:
        Router().navigate(to=href, with_args=params)
