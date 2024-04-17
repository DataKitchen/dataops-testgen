import dataclasses

from testgen.ui.services import authentication_service


@dataclasses.dataclass
class MenuItem:
    icon: str
    label: str
    page: str | None = dataclasses.field(default=None)
    roles: list[authentication_service.RoleType] | None = dataclasses.field(default_factory=list)
    order: int = dataclasses.field(default=0)


@dataclasses.dataclass
class Version:
    current: str
    latest: str
    schema: str


@dataclasses.dataclass
class Menu:
    items: list[MenuItem]
    version: Version

    def filter_for_current_user(self) -> "Menu":
        filtered_items = []
        for menu_item in self.items:
            item_roles = menu_item.roles or []
            if len(item_roles) <= 0 or any(map(authentication_service.current_user_has_role, item_roles)):
                filtered_items.append(menu_item)
        return dataclasses.replace(self, items=filtered_items)

    def sort_items(self) -> "Menu":
        return dataclasses.replace(self, items=sorted(self.items, key=lambda item: item.order))

    def update_version(self, version: Version) -> "Menu":
        return dataclasses.replace(self, version=version)

    def asdict(self):
        return dataclasses.asdict(self)
