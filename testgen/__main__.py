import logging
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import click
from click.core import Context

from testgen import settings
from testgen.commands.run_generate_tests import run_test_gen_queries
from testgen.commands.run_get_entities import (
    run_get_results,
    run_get_test_suite,
    run_list_connections,
    run_list_profiles,
    run_list_projects,
    run_list_test_generation,
    run_list_test_runs,
    run_list_test_suites,
    run_list_test_types,
    run_profile_info,
    run_profile_screen,
    run_table_group_list,
    run_test_info,
)
from testgen.commands.run_launch_db_config import run_launch_db_config
from testgen.commands.run_observability_exporter import run_observability_exporter
from testgen.commands.run_profiling import run_profiling
from testgen.commands.run_quick_start import run_quick_start, run_quick_start_increment
from testgen.commands.run_test_execution import run_test_execution
from testgen.commands.run_test_metadata_exporter import run_test_metadata_exporter
from testgen.commands.run_upgrade_db_config import get_schema_revision, is_db_revision_up_to_date, run_upgrade_db_config
from testgen.common import (
    configure_logging,
    display_service,
    docker_service,
    get_tg_db,
    get_tg_host,
    get_tg_schema,
    version_service,
)
from testgen.common.models import with_database_session
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.settings import PersistedSetting
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.common.notifications.base import smtp_configured
from testgen.common.notifications.profiling_run import send_profiling_run_notifications
from testgen.common.notifications.test_run import send_test_run_notifications
from testgen.scheduler import register_scheduler_job, run_scheduler
from testgen.utils import plugins

LOG = logging.getLogger("testgen")

APP_MODULES = ["ui", "scheduler"]
VERSION_DATA = version_service.get_version()


@dataclass
class Configuration:
    verbose: bool = field(default=False)


# This is just sugar - @pass_obj or @pass_context would work too.
pass_configuration = click.make_pass_decorator(Configuration)


class CliGroup(click.Group):
    def invoke(self, ctx: Context):
        try:
            super().invoke(ctx)
        except Exception:
            LOG.exception("There was an unexpected error")


@click.group(
    cls=CliGroup,
    help=f"""
    {VERSION_DATA.edition} {VERSION_DATA.current or ""}

    {f"New version available! {VERSION_DATA.latest}" if VERSION_DATA.latest != VERSION_DATA.current else ""}

    Schema revision: {get_schema_revision()}
    """
)
@click.option(
    "-v",
    "--verbose",
    help="Enables more detailed logging. If used, must be entered before the command.",
    is_flag=True,
    default=False,
)
@click.pass_context
def cli(ctx: Context, verbose: bool):
    if verbose:
        configure_logging(level=logging.DEBUG)
    else:
        configure_logging(level=logging.INFO)

    ctx.obj = Configuration(verbose=verbose)
    status_ok, message = docker_service.check_basic_configuration()
    if not status_ok:
        click.secho(message, fg="red")
        sys.exit(1)

    if (
        ctx.invoked_subcommand not in ["run-app", "ui", "setup-system-db", "upgrade-system-version", "quick-start"]
        and not is_db_revision_up_to_date()
    ):
        click.secho("The system database schema is outdated. Automatically running the following command:", fg="red")
        click.secho("testgen upgrade-system-version", fg="red")
        do_upgrade_system_version()
        click.secho("\nNow running the requested command...", fg="red")
    LOG.debug("Current Step: Main Program")


@register_scheduler_job
@cli.command("run-profile", help="Generates a new profile of the table group.")
@click.option(
    "-tg",
    "--table-group-id",
    required=True,
    type=click.STRING,
    help="ID of the table group to profile. Use a table_group_id shown in list-table-groups.",
)
def run_profile(table_group_id: str):
    click.echo(f"run-profile with table_group_id: {table_group_id}")
    message = run_profiling(table_group_id)
    click.echo("\n" + message)


@cli.command("run-test-generation", help="Generates or refreshes the tests for a table group.")
@click.option(
    "-tg",
    "--table-group-id",
    help="The identifier for the table group used during a profile run. Use a table_group_id shown in list-table-groups.",
    required=True,
    type=click.STRING,
)
@click.option(
    "-ts",
    "--test-suite-key",
    help="The identifier for a test suite. Use a test_suite_key shown in list-test-suites.",
    required=True,
    type=click.STRING,
)
@click.option(
    "-gs",
    "--generation-set",
    help="A defined subset of tests to generate for your purpose. Use a generation_set defined for your project.",
    required=False,
    default=None,
)
@pass_configuration
def run_test_generation(configuration: Configuration, table_group_id: str, test_suite_key: str, generation_set: str):
    LOG.info("CurrentStep: Generate Tests - Main Procedure")
    message = run_test_gen_queries(table_group_id, test_suite_key, generation_set)
    LOG.info("Current Step: Generate Tests - Main Procedure Complete")
    click.echo("\n" + message)


@register_scheduler_job
@cli.command("run-tests", help="Performs tests defined for a test suite.")
@click.option(
    "-t",
    "--test-suite-id",
    required=False,
    type=click.STRING,
    help="ID of the test suite to run. Use a test_suite_id shown in list-test-suites.",
)
@click.option(
    "-pk",
    "--project-key",
    help="DEPRECATED. Use --test-suite-id instead.",
    required=False,
    type=click.STRING,
    default=settings.PROJECT_KEY,
)
@click.option(
    "-ts",
    "--test-suite-key",
    help="DEPRECATED. Use --test-suite-id instead.",
    required=False,
    default=settings.DEFAULT_TEST_SUITE_KEY,
)
@with_database_session
def run_tests(test_suite_id: str | None = None, project_key: str | None = None, test_suite_key: str | None = None):
    click.echo(f"run-tests for suite: {test_suite_id or test_suite_key}")
    # For backward compatibility
    if not test_suite_id:
        test_suites = TestSuite.select_minimal_where(
            TestSuite.project_code == project_key,
            TestSuite.test_suite == test_suite_key,
        )
        if test_suites:
            test_suite_id = test_suites[0].id
    message = run_test_execution(test_suite_id)
    click.echo("\n" + message)


@cli.command("list-profiles", help="Lists all profile runs for a table group.")
@click.option(
    "-tg",
    "--table-group-id",
    help="The identifier for the table group used during a profile run. Use a table_group_id shown in list-table-groups.",
    required=True,
    type=click.STRING,
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def list_profiles(configuration: Configuration, table_group_id: str, display: bool):
    LOG.info("list_profiles:")
    rows, header = run_list_profiles(table_group_id)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("list_profiles.csv", rows, header)


@cli.command("get-profile", help="Fetches details for a profile run.")
@click.option(
    "-pr",
    "--profile-run-id",
    required=True,
    type=click.STRING,
    help="The identifier for a profile run. Use an ID shown in list-profiles.",
)
@click.option(
    "-tn",
    "--table-name",
    help="Filter the profile run to view details for a single table. Enter the name of a table present in the profile run.",
    type=click.STRING,
    required=False,
    default=None,
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def get_profile(configuration: Configuration, profile_run_id: str, table_name: str, display: bool):
    rows, header = run_profile_info(profile_run_id, table_name)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("get_profile.csv", rows, header)


@cli.command("get-profile-anomalies", help="Fetches details of anomalies that may have occurred for a given profile.")
@click.option(
    "-pr",
    "--profile-run-id",
    required=True,
    type=click.STRING,
    help="The identifier for a profile run. Use an ID shown in list-profiles.",
)
@click.option(
    "-tn",
    "--table-name",
    help="Filter the profile run to view details for a single table. Enter the name of a table present in the profile run.",
    type=click.STRING,
    required=False,
    default=None,
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def get_profile_screen(configuration: Configuration, profile_run_id: str, table_name: str, display: bool):
    rows, header = run_profile_screen(profile_run_id, table_name)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("get_profile_anomalies.csv", rows, header)


@cli.command(
    "list-test-generation",
    help="Lists a summary of test suite generation dates with details for table, column, and test counts.",
)
@click.option(
    "-pk",
    "--project-key",
    required=False,
    type=click.STRING,
    help="The identifier for a TestGen project. Use a project_key shown in list-projects.",
    default=settings.PROJECT_KEY,
)
@click.option(
    "-ts",
    "--test-suite-key",
    help="The identifier for a test suite. Use a test_suite_key shown in list-test-suites.",
    type=click.STRING,
    required=False,
    default=settings.DEFAULT_TEST_SUITE_KEY,
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def list_test_generation(configuration: Configuration, project_key: str, test_suite_key: str, display: bool):
    rows, header = run_list_test_generation(project_key, test_suite_key)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("list_test_generation.csv", rows, header)


@cli.command("list-tests", help="Lists the tests generated for a test suite.")
@click.option(
    "-pk",
    "--project-key",
    required=False,
    type=click.STRING,
    help="The identifier for a TestGen project. Use a project_key shown in list-projects.",
    default=settings.PROJECT_KEY,
)
@click.option(
    "-ts",
    "--test-suite-key",
    help="The identifier for a test suite. Use a test_suite_key shown in list-test-suites.",
    type=click.STRING,
    required=False,
    default=settings.DEFAULT_TEST_SUITE_KEY,
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def get_tests(configuration: Configuration, project_key: str, test_suite_key: str, display: bool):
    rows, header = run_test_info(project_key, test_suite_key)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("list_tests.csv", rows, header)


@cli.command("list-test-runs", help="Lists the test runs performed for a test suite.")
@click.option(
    "-pk",
    "--project-key",
    required=False,
    type=click.STRING,
    help="The identifier for a TestGen project. Use a project_key shown in list-projects.",
    default=settings.PROJECT_KEY,
)
@click.option(
    "-ts",
    "--test-suite-key",
    help="The identifier for a test suite. Use a test_suite_key shown in list-test-suites.",
    type=click.STRING,
    required=False,
    default=settings.DEFAULT_TEST_SUITE_KEY,
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def list_test_runs(configuration: Configuration, project_key: str, test_suite_key: str, display: bool):
    rows, header = run_list_test_runs(project_key, test_suite_key)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("list_test_runs.csv", rows, header)


@cli.command("quick-start", help="Use to generate sample target database, for demo purposes.")
@click.option(
    "--observability-api-url",
    help="Observability API url to be able to export TestGen data to Observability using the command 'export-observability'",
    type=click.STRING,
    required=False,
    default="",
)
@click.option(
    "--observability-api-key",
    help="Observability API key to be able to export TestGen data to Observability using the command 'export-observability'",
    type=click.STRING,
    required=False,
    default="",
)
@pass_configuration
@click.pass_context
def quick_start(
    ctx: Context,
    configuration: Configuration,
    observability_api_url: str,
    observability_api_key: str,
):
    if observability_api_url:
        settings.OBSERVABILITY_API_URL = observability_api_url
    if observability_api_key:
        settings.OBSERVABILITY_API_KEY = observability_api_key

    click.echo("quick-start command")
    run_quick_start(delete_target_db=True)

    click.echo("loading initial data")
    run_quick_start_increment(0)
    now_date = datetime.now(UTC)
    time_delta = timedelta(days=-30) # 1 month ago
    table_group_id = "0ea85e17-acbe-47fe-8394-9970725ad37d"
    test_suite_id = "9df7489d-92b3-49f9-95ca-512160d7896f"

    click.echo(f"run-profile with table_group_id: {table_group_id}")
    message = run_profiling(table_group_id, run_date=now_date + time_delta)
    click.echo("\n" + message)

    LOG.info(f"run-test-generation with table_group_id: {table_group_id} test_suite: {settings.DEFAULT_TEST_SUITE_KEY}")
    message = run_test_gen_queries(table_group_id, settings.DEFAULT_TEST_SUITE_KEY)
    click.echo("\n" + message)

    run_test_execution(test_suite_id, run_date=now_date + time_delta)

    total_iterations = 3
    for iteration in range(1, total_iterations + 1):
        click.echo(f"Running iteration: {iteration} / {total_iterations}")
        run_date = now_date + timedelta(days=-10 * (total_iterations - iteration)) # 10 day increments
        run_quick_start_increment(iteration)
        run_test_execution(test_suite_id, run_date=run_date)

    click.echo("Quick start has successfully finished.")


@cli.command("setup-system-db", help="Use to initialize the TestGen system database.")
@click.option(
    "--delete-db",
    help="Will delete the current system database, if it exists",
    is_flag=True,
    default=False,
)
@click.option("--yes", "-y", default=False, is_flag=True, required=False, help="Force yes")
@pass_configuration
def setup_app_db(configuration: Configuration, delete_db: bool, yes: bool):
    click.echo("setup-system-db command")

    db = get_tg_db()
    host = get_tg_host()
    schema = get_tg_schema()

    if not yes:
        operation_message = "create"

        if delete_db:
            warning_text = "WARNING: This command will delete any existing TestGen data, drop the current TestGen app database, and create a new copy from scratch. "
            click.secho(warning_text, fg="red")

            operation_message = "DELETE and recreate"

        message = f"Are you SURE you want to {operation_message} the app database '{db}' in the host '{host}'?"
        if not click.confirm(click.style(message, fg="red")):
            click.echo("Exiting without any operation performed.")
            return

    run_launch_db_config(delete_db)

    projectDetails = {
        "project_key": settings.PROJECT_KEY,
        "sql_flavor": settings.PROJECT_SQL_FLAVOR,
        "project_name": settings.PROJECT_NAME,
        "project_db_name": settings.PROJECT_DATABASE_NAME,
        "project_db_user": settings.PROJECT_DATABASE_USER,
        "project_db_port": settings.PROJECT_DATABASE_PORT,
        "project_db_host": settings.PROJECT_DATABASE_HOST,
        "project_db_schema": settings.PROJECT_DATABASE_SCHEMA,
    }
    click.echo(f"App DB created: Host={host}, DB Name={db}, Schema={schema}")
    click.echo(f"Project Details:{projectDetails}")
    click.echo("setup-system-db has successfully finished.")


@cli.command(
    "upgrade-system-version", help="Upgrades your system and services to match the current DataOps TestGen version."
)
@pass_configuration
def upgrade_system_version(configuration: Configuration):
    do_upgrade_system_version()


def do_upgrade_system_version():
    LOG.info("setup_app_db command")

    if run_upgrade_db_config():
        click.echo("System and services were upgraded to match current TestGen version.")
    else:
        click.echo("System and services upgrade is not required.")


@cli.command("get-test-results", help="Fetches results for a test run.")
@click.option(
    "-tr",
    "--test-run-id",
    required=True,
    type=click.STRING,
    help="The identifier for a test run. Use a test_run_id shown in list-test-runs.",
)
@click.option(
    "-f", "--fails-only", help="Filter test results to view only failed outcomes.", is_flag=True, default=False
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def get_results(configuration: Configuration, test_run_id: str, fails_only: bool, display: bool):
    rows, header = run_get_results(test_run_id, fails_only)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("get_test_results.csv", rows, header)


@cli.command("export-observability", help="Sends test results from TestGen to DataOps Observability.")
@click.option(
    "-pk",
    "--project-key",
    help="The identifier for a TestGen project. Use a project_key shown in list-projects.",
    required=False,
    type=click.STRING,
    default=settings.PROJECT_KEY,
)
@click.option(
    "-ts",
    "--test-suite-key",
    help="The identifier for a test suite. Use a test_suite_key shown in list-test-suites.",
    required=False,
    default=settings.DEFAULT_TEST_SUITE_KEY,
)
@pass_configuration
def export_data(configuration: Configuration, project_key: str, test_suite_key: str):
    click.echo(f"export-observability for test suite: {test_suite_key}")
    LOG.info("CurrentStep: Main Program - Observability Export")
    run_observability_exporter(project_key, test_suite_key)
    LOG.info("CurrentStep: Main Program - Observability Export - DONE")
    click.echo("\nexport-observability completed successfully.\n")


@click.option(
    "--path",
    help="Path to the templates folder. Defaults to path from project root.",
    required=False,
    default="testgen/template",
)
@cli.command("export-test-metadata", help="Exports current test metadata records to yaml files.")
@pass_configuration
def export_test_metadata(configuration: Configuration, path: str):
    click.echo("export-test-metadata")
    LOG.info("CurrentStep: Main Program - Test Metadata Export")
    if not os.path.isdir(path):
        LOG.error(f"Provided path {path} is not a directory. Please correct the --path option.")
        return
    run_test_metadata_exporter(path)
    LOG.info("CurrentStep: Main Program - Test Metadata Export - DONE")
    click.echo("\nexport-test-metadata completed successfully.\n")


@cli.command("list-test-types", help="Lists all available TestGen test types.")
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def list_test_types(configuration: Configuration, display: bool):
    rows, header = run_list_test_types()
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("list_test_types.csv", rows, header)


@cli.command("list-projects", help="Lists all projects in the tenant.")
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def list_projects(configuration: Configuration, display: bool):
    rows, header = run_list_projects()
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("list_projects.csv", rows, header)


@cli.command("list-connections", help="Lists all database connections in the tenant.")
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def list_connections(configuration: Configuration, display: bool):
    rows, header = run_list_connections()
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("list_connections.csv", rows, header)


@cli.command("get-test-suite", help="Fetches details for a test suite.")
@click.option(
    "-pk",
    "--project-key",
    required=False,
    type=click.STRING,
    help="The identifier for a TestGen project. Use a project_key shown in list-projects.",
    default=settings.PROJECT_KEY,
)
@click.option(
    "-ts",
    "--test-suite-key",
    help="The identifier for a test suite. Use a test_suite_key shown in list-test-suites.",
    type=click.STRING,
    required=False,
    default=None,
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def get_test_suite(configuration: Configuration, project_key: str, test_suite_key: str, display: bool):
    rows, header = run_get_test_suite(project_key, test_suite_key)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("get_test_suite.csv", rows, header)


@cli.command("list-test-suites", help="Lists the test suites in a project.")
@click.option(
    "-pk",
    "--project-key",
    required=False,
    type=click.STRING,
    help="The identifier for a TestGen project. Use a project_key shown in list-projects.",
    default=settings.PROJECT_KEY,
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def list_test_suites(configuration: Configuration, project_key: str, display: bool):
    rows, header = run_list_test_suites(project_key)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("list_test_suites.csv", rows, header)


@cli.command("list-table-groups", help="Lists the tables groups in a project.")
@click.option(
    "-pk",
    "--project-key",
    required=False,
    type=click.STRING,
    help="The identifier for a TestGen project. Use a project_key shown in list-projects.",
    default=settings.PROJECT_KEY,
)
@click.option("-d", "--display", help="Show command output in the terminal.", is_flag=True, default=False)
@pass_configuration
def list_table_groups(configuration: Configuration, project_key: str, display: bool):
    rows, header = run_table_group_list(project_key)
    if display:
        display_service.print_table(rows, header)
    display_service.to_csv("list_table_groups.csv", rows, header)


@cli.group("ui", help="Manage the browser application")
def ui(): ...


@ui.command("plugins", help="List installed application plugins")
def list_ui_plugins():
    installed_plugins = list(plugins.discover())

    click.echo(click.style(len(installed_plugins), fg="bright_magenta") + click.style(" plugins installed", bold=True))
    for plugin in installed_plugins:
        click.echo(click.style(" + ", fg="bright_green") + f"{plugin.package: <30}" + f"\tversion: {plugin.version}")


def run_ui():
    from testgen.ui.scripts import patch_streamlit

    use_ssl = os.path.isfile(settings.SSL_CERT_FILE) and os.path.isfile(settings.SSL_KEY_FILE)

    patch_streamlit.patch(force=True)

    @with_database_session
    def init_ui():
        try:
            for profiling_run_id in ProfilingRun.cancel_all_running():
                send_profiling_run_notifications(ProfilingRun.get(profiling_run_id))
            for test_run_id in TestRun.cancel_all_running():
                send_test_run_notifications(TestRun.get(test_run_id))
        except Exception:
            LOG.warning("Failed to cancel 'Running' profiling/test runs")

        PersistedSetting.set("SMTP_CONFIGURED", smtp_configured())

    init_ui()

    app_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui/app.py")
    process= subprocess.Popen(
        [  # noqa: S607
            "streamlit",
            "run",
            app_file,
            "--browser.gatherUsageStats=false",
            "--client.showErrorDetails=none",
            "--client.toolbarMode=minimal",
            f"--server.sslCertFile={settings.SSL_CERT_FILE}" if use_ssl else "",
            f"--server.sslKeyFile={settings.SSL_KEY_FILE}" if use_ssl else "",
            "--",
            f"{'--debug' if settings.IS_DEBUG else ''}",
        ],
        env={**os.environ, "TG_JOB_SOURCE": "UI"}
    )
    def term_ui(signum, _):
        LOG.info(f"Sending termination signal {signum} to Testgen UI")
        process.send_signal(signum)
    signal.signal(signal.SIGINT, term_ui)
    signal.signal(signal.SIGTERM, term_ui)
    status_code = process.wait()
    LOG.log(logging.ERROR if status_code != 0 else logging.INFO, f"Testgen UI exited with status code {status_code}")


@cli.command("run-app", help="Runs TestGen's application modules")
@click.argument(
    "module",
    type=click.Choice(["all", *APP_MODULES]),
    default="all",
)
def run_app(module):

    match module:
        case "ui":
            run_ui()

        case "scheduler":
            run_scheduler()

        case "all":
            children = [
                subprocess.Popen([sys.executable, sys.argv[0], "run-app", m], start_new_session=True)
                for m in APP_MODULES
            ]

            def term_children(signum, _):
                for child in children:
                    child.send_signal(signum)

            signal.signal(signal.SIGINT, term_children)
            signal.signal(signal.SIGTERM, term_children)

            for child in children:
                child.wait()


if __name__ == "__main__":
    cli()
