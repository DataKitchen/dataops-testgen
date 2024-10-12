import typing

from testgen.ui.components.utils.component import component

ButtonType = typing.Literal["basic", "flat", "icon", "stroked"]
TooltipPosition = typing.Literal["left", "right"]


def button(
    type_: ButtonType = "basic",
    label: str | None = None,
    icon: str | None = None,
    tooltip: str | None = None,
    tooltip_position: TooltipPosition = "left",
    on_click: typing.Callable[..., None] | None = None,
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

    props = {"type": type_}
    if type_ != "icon":
        if not label:
            raise ValueError(f"A label is required for {type_} buttons")
        props.update({"label": label})

    if icon:
        props.update({"icon": icon})

    if tooltip:
        props.update({"tooltip": tooltip, "tooltipPosition": tooltip_position})

    if style:
        props.update({"style": style})

    return component(id_="button", key=key, props=props, on_change=on_click)
