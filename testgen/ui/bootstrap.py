import dataclasses
import importlib
import inspect
import logging

import streamlit as st

from testgen import settings
from testgen.commands.run_upgrade_db_config import get_schema_revision
from testgen.common import configure_logging, version_service
from testgen.ui.assets import get_asset_path
from testgen.ui.navigation.menu import Menu, Version
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.session import session
from testgen.ui.views.connections import ConnectionsPage
from testgen.ui.views.data_catalog import DataCatalogPage
from testgen.ui.views.hygiene_issues import HygieneIssuesPage
from testgen.ui.views.login import LoginPage
from testgen.ui.views.profiling_results import ProfilingResultsPage
from testgen.ui.views.profiling_runs import DataProfilingPage
from testgen.ui.views.project_dashboard import ProjectDashboardPage
from testgen.ui.views.project_settings import ProjectSettingsPage
from testgen.ui.views.quality_dashboard import QualityDashboardPage
from testgen.ui.views.score_details import ScoreDetailsPage
from testgen.ui.views.score_explorer import ScoreExplorerPage
from testgen.ui.views.table_groups import TableGroupsPage
from testgen.ui.views.test_definitions import TestDefinitionsPage
from testgen.ui.views.test_results import TestResultsPage
from testgen.ui.views.test_runs import TestRunsPage
from testgen.ui.views.test_suites import TestSuitesPage
from testgen.utils import plugins, singleton

BUILTIN_PAGES: list[type[Page]] = [
    LoginPage,
    ProjectDashboardPage,
    QualityDashboardPage,
    ScoreDetailsPage,
    ScoreExplorerPage,
    DataCatalogPage,
    DataProfilingPage,
    ProfilingResultsPage,
    HygieneIssuesPage,
    TestRunsPage,
    TestResultsPage,
    ConnectionsPage,
    TableGroupsPage,
    TestSuitesPage,
    TestDefinitionsPage,
    ProjectSettingsPage,
]

LOG = logging.getLogger("testgen")


class Logo:
    image_path: str = get_asset_path("dk_logo.svg")
    icon_path: str = get_asset_path("dk_icon.svg")

    def render(self):
        st.logo(
            image=self.image_path,
            icon_image=self.icon_path,
        )


class Application(singleton.Singleton):
    def __init__(self, logo: Logo, router: Router, menu: Menu, logger: logging.Logger) -> None:
        self.logo = logo
        self.router = router
        self.menu = menu
        self.logger = logger

    def get_version(self) -> Version:
        latest_version = self.menu.version.latest
        if not session.latest_version:
            latest_version = version_service.get_latest_version()

        return Version(
            current=settings.VERSION,
            latest=latest_version,
            schema=get_schema_revision(),
        )


def run(log_level: int = logging.INFO) -> Application:
    pages = [*BUILTIN_PAGES]
    installed_plugins = plugins.discover()

    configure_logging(level=log_level)
    logo_class = Logo

    for plugin in installed_plugins:
        module = importlib.import_module(plugin.package)
        for property_name in dir(module):
            if (
                (maybe_class := getattr(module, property_name, None))
                and inspect.isclass(maybe_class)
            ):
                if issubclass(maybe_class, Page):
                    pages.append(maybe_class)
                elif issubclass(maybe_class, Logo):
                    logo_class = maybe_class

    return Application(
        logo=logo_class(),
        router=Router(routes=pages),
        menu=Menu(
            items=list(
                {
                    page.path: dataclasses.replace(page.menu_item, page=page.path)
                    for page in pages if page.menu_item
                }.values()
            ),
            version=Version(
                current=settings.VERSION,
                latest="...",
                schema=get_schema_revision(),
            ),
        ),
        logger=LOG,
    )
