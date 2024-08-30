import typing

from testgen.ui.components.utils.component import component

ButtonType = typing.Literal["basic", "flat", "icon", "stroked"]
TooltipPosition = typing.Literal["left", "right"]


def button(
    type: ButtonType = "basic",
    label: str | None = None,
    icon: str | None = None,
    tooltip: str | None = None,
    tooltip_position: TooltipPosition = "left",
    on_click: typing.Callable[..., None] | None = None,
    key: str | None = None,
) -> None:
    """
    Testgen component to create custom styled buttons.

    # Parameters
    :param key: unique key to give the component a persisting state
    :param icon: icon name of material rounded icon fonts
    :param on_click: click handler for this button
    """

    props = {"type": type}
    if type != "icon":
        if not label:
            raise ValueError(f"A label is required for {type} buttons")
        props.update({"label": label})

    if icon:
        props.update({"icon": icon})

    if tooltip:
        props.update({"tooltip": tooltip, "tooltipPosition": tooltip_position})

    component(id_="button", key=key, props=props, on_change=on_click)
