from __future__ import annotations

import abc
import logging
import typing

import streamlit as st

import testgen.ui.navigation.router
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.session import session

CanActivateGuard = typing.Callable[[], bool | str]
LOG = logging.getLogger("testgen")


class Page(abc.ABC):
    path: str
    menu_item: MenuItem | None = None
    can_activate: typing.ClassVar[list[CanActivateGuard] | None] = None

    def __init__(self, router: testgen.ui.navigation.router.Router) -> None:
        self.router = router
        self.streamlit_page = st.Page(self._navigate, url_path=self.path, title=self.path, default=not self.path)

        if "/" in self.path:
            st.error(f"Cannot use multi-level path '{self.path}' in current Streamlit version: https://github.com/streamlit/streamlit/issues/8971")
            st.stop()

    def _navigate(self) -> None:
        for guard in self.can_activate or []:
            can_activate = guard()
            if type(can_activate) == str:
                return self.router.navigate(to=can_activate)

            if not can_activate:
                session.page_pending_login = self.path
                return self.router.navigate(to="")

        self.render(**(session.current_page_args or {}))

    @abc.abstractmethod
    def render(self, **kwargs) -> None:
        raise NotImplementedError
