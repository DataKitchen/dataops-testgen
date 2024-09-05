import dataclasses
import importlib
import inspect
import logging

from testgen import settings
from testgen.commands.run_upgrade_db_config import get_schema_revision
from testgen.common import configure_logging, version_service
from testgen.ui.navigation.menu import Menu, Version
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.session import session
from testgen.ui.views.connections import ConnectionsPage
from testgen.ui.views.login import LoginPage
from testgen.ui.views.overview import OverviewPage
from testgen.ui.views.profiling_anomalies import ProfilingAnomaliesPage
from testgen.ui.views.profiling_results import ProfilingResultsPage
from testgen.ui.views.profiling_summary import DataProfilingPage
from testgen.ui.views.project_settings import ProjectSettingsPage
from testgen.ui.views.table_groups import TableGroupsPage
from testgen.ui.views.test_definitions import TestDefinitionsPage
from testgen.ui.views.test_results import TestResultsPage
from testgen.ui.views.test_runs import TestRunsPage
from testgen.ui.views.test_suites import TestSuitesPage
from testgen.utils import plugins, singleton

BUILTIN_PAGES: list[type[Page]] = [
    LoginPage,
    OverviewPage,
    DataProfilingPage,
    ProfilingResultsPage,
    ProfilingAnomaliesPage,
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
    def __init__(self, router: Router, menu: Menu, logger: logging.Logger) -> None:
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

    for plugin in installed_plugins:
        module = importlib.import_module(plugin.package)
        for property_name in dir(module):
            if (
                (maybe_page := getattr(module, property_name, None))
                and inspect.isclass(maybe_page)
                and issubclass(maybe_page, Page)
            ):
                pages.append(maybe_page)

    return Application(
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
