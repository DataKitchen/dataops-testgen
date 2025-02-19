import typing

from testgen.ui.components.utils.component import component

ButtonType = typing.Literal["basic", "flat", "icon", "stroked"]
ButtonColor = typing.Literal["basic", "primary", "warn"]
TooltipPosition = typing.Literal["left", "right"]


def button(
    type_: ButtonType = "basic",
    color: ButtonColor | None = None,
    label: str | None = None,
    icon: str | None = None,
    icon_size: int | None = None,
    tooltip: str | None = None,
    tooltip_position: TooltipPosition = "left",
    on_click: typing.Callable[..., None] | None = None,
    disabled: bool = False,
    width: str | int | float | None = None,
    style: str | None = None,
    key: str | None = None,
) -> typing.Any:
    """
    Testgen component to create custom styled buttons.

    # Parameters
    :param key: unique key to give the component a persisting state
    :param icon: icon name of material rounded icon fonts
    :param on_click: click handler for this button
    """
    color_ = color or "primary"
    if not color and type_ == "icon":
        color_ = "basic"

    props = {"type": type_, "disabled": disabled, "color": color_}
    if type_ != "icon":
        if not label:
            raise ValueError(f"A label is required for {type_} buttons")
        props.update({"label": label})

    if icon:
        props.update({"icon": icon, "iconSize": icon_size})

    if tooltip:
        props.update({"tooltip": tooltip, "tooltipPosition": tooltip_position})

    if width:
        props.update({"width": width})
        if isinstance(width, int | float):
            props.update({"width": f"{width}px"})

    if style:
        props.update({"style": style})

    return component(id_="button", key=key, props=props, on_change=on_click)
