import dataclasses
import typing

from testgen.ui.services import user_session_service

MenuSections = typing.Literal["Data Profiling", "Data Quality Testing", "Data Configuration", "Settings"]


@dataclasses.dataclass
class MenuItem:
    label: str
    icon: str | None = dataclasses.field(default=None)
    page: str | None = dataclasses.field(default=None)
    roles: list[user_session_service.RoleType] | None = dataclasses.field(default_factory=list)
    order: int = dataclasses.field(default=0)
    section: MenuSections | None = dataclasses.field(default=None)
    items: list["MenuItem"] | None = dataclasses.field(default=None)


@dataclasses.dataclass
class Menu:
    items: list[MenuItem]

    def filter_for_current_user(self) -> "Menu":
        filtered_items = []
        for menu_item in self.items:
            item_roles = menu_item.roles or []
            if len(item_roles) <= 0 or any(map(user_session_service.user_has_role, item_roles)):
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
