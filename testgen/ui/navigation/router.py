from __future__ import annotations

import logging
import typing

import streamlit as st

import testgen.ui.navigation.page
from testgen.utils.singleton import Singleton

CanActivateGuard = typing.Callable[[], bool | str]

LOG = logging.getLogger("testgen")


class Router(Singleton):
    active: testgen.ui.navigation.page.Page | None
    _default: type[testgen.ui.navigation.page.Page] | None
    _routes: dict[str, type[testgen.ui.navigation.page.Page]]

    def __init__(
        self,
        /,
        routes: list[type[testgen.ui.navigation.page.Page]],
        default: type[testgen.ui.navigation.page.Page] | None = None,
    ) -> None:
        self._routes = {}

        for route in routes:
            self._routes[route.path] = route

        self.active = None
        self._default = default
        if self._default:
            self._routes[self._default.path] = self._default

    def navigate(self, /, to: str, with_args: dict | None = None) -> None:
        try:
            route = self._routes[to]

            bc_source = route(self).path

            for guard in route.can_activate or []:
                can_activate = guard()
                if type(can_activate) == str:
                    return self.navigate(to=can_activate, with_args={})

                if not can_activate and self._default:
                    return self.navigate(to=self._default.path, with_args=with_args)

            if not isinstance(self.active, route):
                self.active = route(self)

            self.active.render(**(with_args or {}))
        except KeyError as k:
            error_message = f"{bc_source}: {k!s}"
            st.error(error_message)
            LOG.exception(error_message)
            return self.navigate(to=self._default.path, with_args=with_args)
        except Exception as e:
            error_message = f"{bc_source}: {e!s}"
            st.error(error_message)
            LOG.exception(error_message)
