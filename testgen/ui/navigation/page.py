import abc
import typing

import testgen.ui.navigation.router
from testgen.ui.navigation.menu import MenuItem

CanActivateGuard = typing.Callable[[], bool | str]


class Page(abc.ABC):
    path: str
    menu_item: MenuItem | None = None
    can_activate: typing.ClassVar[list[CanActivateGuard] | None] = None

    def __init__(self, router: testgen.ui.navigation.router.Router) -> None:
        self.router = router

    @abc.abstractmethod
    def render(self, **kwargs) -> None:
        raise NotImplementedError
