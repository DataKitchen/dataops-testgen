import dataclasses
import logging

from testgen import settings
from testgen.common import configure_logging
from testgen.ui.navigation.menu import Menu
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
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


class Application(singleton.Singleton):
    def __init__(self, logo: plugins.Logo, router: Router, menu: Menu, logger: logging.Logger) -> None:
        self.logo = logo
        self.router = router
        self.menu = menu
        self.logger = logger


def run(log_level: int = logging.INFO) -> Application:
    pages = [*BUILTIN_PAGES]
    installed_plugins = plugins.discover()

    if not settings.IS_DEBUG:
        """
        This cleanup is called so that TestGen can remove uninstalled
        plugins without having to be reinstalled.

        The check for DEBUG mode is because multithreading for Streamlit
        fragments loads before the plugins can be re-loaded.
        """
        plugins.cleanup()

    configure_logging(level=log_level)
    logo_class = plugins.Logo

    for plugin in installed_plugins:
        spec = plugin.load()

        if spec.page:
            pages.append(spec.page)

        if spec.logo:
            logo_class = spec.logo

        if spec.component:
            spec.component.provide()

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
        ),
        logger=LOG,
    )
