from __future__ import annotations

import abc
import logging
import typing

import streamlit as st
from streamlit.runtime.state.query_params_proxy import QueryParamsProxy

import testgen.ui.navigation.router
from testgen.common.models.project import Project
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
        self.router.navigate_to_pending()
        for guard in self.can_activate or []:
            can_activate = guard()
            if can_activate != True:
                session.sidebar_project = session.sidebar_project or Project.select_where()[0].project_code

                if type(can_activate) == str:
                    return self.router.navigate(to=can_activate, with_args={ "project_code": session.sidebar_project })

                session.page_pending_login = self.path
                session.page_args_pending_login = st.query_params.to_dict()

                default_page = session.user_default_page or ""
                with_args = { "project_code": session.sidebar_project } if default_page else {}
                return self.router.navigate(to=default_page, with_args=with_args)

        self.render(**self._query_params_to_kwargs(st.query_params))

    def _query_params_to_kwargs(self, query_params: dict | QueryParamsProxy) -> dict:
        if not isinstance(query_params, QueryParamsProxy):
            return query_params

        kwargs = {}
        for key in query_params.keys():
            values_list = query_params.get_all(key)
            kwargs[key] = values_list if len(values_list) > 1 else query_params.get(key)
        return kwargs

    @abc.abstractmethod
    def render(self, **kwargs) -> None:
        raise NotImplementedError
