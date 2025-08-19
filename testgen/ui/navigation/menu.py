import dataclasses
import typing

from testgen.ui.auth import Permission
from testgen.ui.session import session

MenuSections = typing.Literal["Data Profiling", "Data Quality Testing", "Data Configuration", "Settings"]


@dataclasses.dataclass
class MenuItem:
    label: str
    icon: str | None = dataclasses.field(default=None)
    page: str | None = dataclasses.field(default=None)
    permission: Permission = dataclasses.field(default="view")
    order: int = dataclasses.field(default=0)
    section: MenuSections | None = dataclasses.field(default=None)
    items: list["MenuItem"] | None = dataclasses.field(default=None)


@dataclasses.dataclass
class Menu:
    items: list[MenuItem]

    def filter_for_current_user(self) -> "Menu":
        filtered_items = []
        for menu_item in self.items:
            item_permission = menu_item.permission or "view"
            if session.auth.user_has_permission(item_permission):
                filtered_items.append(menu_item)
        return dataclasses.replace(self, items=filtered_items)

    def sort_items(self) -> "Menu":
        return dataclasses.replace(self, items=sorted(self.items, key=lambda item: item.order))

    def unflatten(self) -> "Menu":
        unflattened_items = []
        section_items = { section: [] for section in typing.get_args(MenuSections) }
        for menu_item in self.items:
            if menu_item.section:
                section_items[menu_item.section].append(menu_item)
            else:
                unflattened_items.append(menu_item)
        for label, items in section_items.items():
            if items:
                unflattened_items.append(MenuItem(label=label, items=items))
        return dataclasses.replace(self, items=unflattened_items)

    def asdict(self):
        return dataclasses.asdict(self)
