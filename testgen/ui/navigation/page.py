from __future__ import annotations

import abc
import logging
import typing

import streamlit as st
from streamlit.runtime.state.query_params_proxy import QueryParamsProxy

import testgen.ui.navigation.router
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.services import project_service
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
            if type(can_activate) == str:
                return self.router.navigate(to=can_activate)

            if not can_activate:
                session.page_pending_login = self.path
                return self.router.navigate(to=session.user_default_page or "")

        session.current_page_args = session.current_page_args or {}
        self._validate_project_query_param()

        self.render(**self._query_params_to_kwargs(session.current_page_args))

    def _query_params_to_kwargs(self, query_params: dict | QueryParamsProxy) -> dict:
        if not isinstance(query_params, QueryParamsProxy):
            return query_params

        kwargs = {}
        for key in query_params.keys():
            values_list = query_params.get_all(key)
            kwargs[key] = values_list if len(values_list) > 1 else query_params.get(key)
        return kwargs

    def _validate_project_query_param(self) -> None:
        if self.path != "" and ":" not in self.path:
            project_param = session.current_page_args.get("project_code")
            valid_project_codes = [ project["code"] for project in project_service.get_projects() ]

            if project_param not in valid_project_codes: # Ensure top-level pages have valid project_code
                session.current_page_args.update({ "project_code": session.project})
                self.router.set_query_params({ "project_code": session.project})
            elif project_param != session.project: # Sync session state with query param
                project_service.set_current_project(project_param)
        else:
            session.current_page_args.pop("project_code", None)

    @abc.abstractmethod
    def render(self, **kwargs) -> None:
        raise NotImplementedError
