from __future__ import annotations

import abc
import logging
import typing

import streamlit as st
from streamlit.runtime.state.query_params_proxy import QueryParamsProxy

import testgen.ui.navigation.router
from testgen.ui.auth import Permission
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.session import session

CanActivateGuard = typing.Callable[[], bool | str]
LOG = logging.getLogger("testgen")


class Page(abc.ABC):
    path: str
    menu_item: MenuItem | None = None
    permission: Permission | None = "view"
    can_activate: typing.ClassVar[list[CanActivateGuard] | None] = None

    def __init__(self, router: testgen.ui.navigation.router.Router) -> None:
        self.router = router
        self.streamlit_page = st.Page(self._navigate, url_path=self.path, title=self.path, default=not self.path)

        if "/" in self.path:
            st.error(f"Cannot use multi-level path '{self.path}' in current Streamlit version: https://github.com/streamlit/streamlit/issues/8971")
            st.stop()

    def _navigate(self) -> None:
        self.router.navigate_to_pending()

        is_admin_page = self.permission == "global_admin"
        requested_project = st.query_params.get("project_code")
        if not is_admin_page and session.auth.user and requested_project and not session.auth.user_has_project_access(requested_project):
            default_page = session.auth.get_default_page()
            project_codes = session.auth.user.get_accessible_projects()
            return self.router.navigate_with_warning(
                "You do not have access to this project or it does not exist. Redirecting ...",
                to=default_page,
                with_args={"project_code": project_codes[0] if project_codes else None},
            )

        sidebar_project = session.sidebar_project
        if not sidebar_project and session.auth.user:
            project_codes = [requested_project] if requested_project else session.auth.user.get_accessible_projects()
            sidebar_project = project_codes[0] if project_codes else None
        session.sidebar_project = sidebar_project

        permission_guard = lambda: session.auth.user_has_permission(self.permission) if self.permission else True
        for guard in [ permission_guard, *(self.can_activate or []) ]:
            can_activate = guard()
            if can_activate != True:
                if type(can_activate) == str:
                    return self.router.navigate(to=can_activate, with_args={ "project_code": session.sidebar_project })

                session.page_pending_login = self.path
                session.page_args_pending_login = st.query_params.to_dict()

                default_page = session.auth.get_default_page(project_code=session.sidebar_project)
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
