import getpass
import logging
import os
import subprocess
import sys
import typing
from dataclasses import dataclass, field

import click
from click.core import Context
from progress.spinner import MoonSpinner
from trogon import tui

from testgen import settings
from testgen.commands.run_execute_tests import run_execution_steps
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
from testgen.commands.run_profiling_bridge import run_profiling_queries
from testgen.commands.run_quick_start import run_quick_start, run_quick_start_increment
from testgen.commands.run_setup_profiling_tools import run_setup_profiling_tools
from testgen.commands.run_upgrade_db_config import get_schema_revision, is_db_revision_up_to_date, run_upgrade_db_config
from testgen.common import (
    configure_logging,
    display_service,
    docker_service,
    get_tg_db,
    get_tg_host,
    get_tg_schema,
    logs,
    version_service,
)
from testgen.utils import plugins

LOG = logging.getLogger("testgen")


@dataclass
class Configuration:
    verbose: bool = field(default=False)


# This is just sugar - @pass_obj or @pass_context would work too.
pass_configuration = click.make_pass_decorator(Configuration)


@tui()
@click.group(
    help=f"This version: {settings.VERSION} \n\nLatest version: {version_service.get_latest_version()} \n\nSchema revision: {get_schema_revision()}"
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
        ctx.invoked_subcommand not in ["ui", "tui", "setup-system-db", "upgrade-system-version", "quick-start"]
        and not is_db_revision_up_to_date()
    ):
        click.secho("The system database schema is outdated. Automatically running the following command:", fg="red")
        click.secho("testgen upgrade-system-version", fg="red")
        do_upgrade_system_version()
        click.secho("\nNow running the requested command...", fg="red")
    LOG.debug("Current Step: Main Program")


@cli.command("run-profile", help="Generates a new profile of the table group.")
@pass_configuration
@click.option(
    "-tg",
    "--table-group-id",
    required=False,
    type=click.STRING,
    help="The identifier for the table group used during a profile run. Use a table_group_id shown in list-table-groups.",
    default=None,
)
def run_profile(configuration: Configuration, table_group_id: str):
    click.echo(f"run-profile with table_group_id: {table_group_id}")
    spinner = None
    if not configuration.verbose:
        spinner = MoonSpinner("Processing ... ")
    message = run_profiling_queries(table_group_id, spinner=spinner)
    click.echo("\n" + message)


@cli.command("run-test-generation", help="Generates or refreshes the tests for a table group.")
@click.option(
    "-tg",
    "--table-group-id",
    help="The identifier for the table group used during a profile run. Use a table_group_id shown in list-table-groups.",
    required=False,
    type=click.STRING,
    default=None,
)
@click.option(
    "-ts",
    "--test-suite-key",
    help="The identifier for a test suite. Use a test_suite_key shown in list-test-suites.",
    required=False,
    default=settings.DEFAULT_TEST_SUITE_KEY,
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


@cli.command("run-tests", help="Performs tests defined for a test suite.")
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
def run_tests(configuration: Configuration, project_key: str, test_suite_key: str):
    click.echo(f"run-tests for suite: {test_suite_key}")
    spinner = None
    if not configuration.verbose:
        spinner = MoonSpinner("Processing ... ")
    message = run_execution_steps(project_key, test_suite_key, spinner=spinner)
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
    "--delete-target-db",
    help="Will delete the current target database, if it exists",
    is_flag=True,
    default=False,
)
@click.option(
    "--iteration",
    "-i",
    default=0,
    required=False,
    help="The monthly data increment snapshot. Can be 0, 1, 2 or 3. 0 is the initial data.",
)
@click.option(
    "--simulate-fast-forward",
    "-s",
    default=False,
    is_flag=True,
    required=False,
    help="For demo purposes, simulates that some time pass by and the target data is changing. This will call the iterations in order.",
)
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
def quick_start(
    configuration: Configuration,
    delete_target_db: bool,
    iteration: int,
    simulate_fast_forward: bool,
    observability_api_url: str,
    observability_api_key: str,
):
    if observability_api_url:
        settings.OBSERVABILITY_API_URL = observability_api_url
    if observability_api_key:
        settings.OBSERVABILITY_API_KEY = observability_api_key

    # Check if this is an increment or the initial state
    if iteration == 0 and not simulate_fast_forward:
        click.echo("quick-start command")
        run_quick_start(delete_target_db)

    if not simulate_fast_forward:
        run_quick_start_increment(iteration)
    else:
        for iteration in range(1, 4):
            click.echo(f"Running iteration: {iteration} / 3")
            minutes_offset = 2 * iteration
            run_quick_start_increment(iteration)
            run_execution_steps(settings.PROJECT_KEY, settings.DEFAULT_TEST_SUITE_KEY, minutes_offset=minutes_offset)

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


@cli.command(
    "setup-target-db-functions", help="Use to set up the utility functions in the target database for running profiles."
)
@click.option(
    "-c",
    "--connection-id",
    help="The identifier for the connection. Use a connection_id shown in list-connections.",
    required=True,
    type=click.STRING,
)
@click.option(
    "-dr",
    "--dry-run",
    default=False,
    is_flag=True,
    required=False,
    help="Dry run to show which schema will be modified",
)
@click.option(
    "-cs",
    "--create-qc-schema",
    default=False,
    is_flag=True,
    required=False,
    help="Create the QC utility schema required in the target database",
)
@click.option("--yes", "-y", default=False, is_flag=True, required=False, help="Force yes")
@click.option(
    "--skip-asking-credentials",
    "-s",
    default=False,
    is_flag=True,
    required=False,
    help="Skip request for special write credentials for target database, uses standard credentials instead",
)
@click.option(
    "--skip-granting-privileges",
    "-sgp",
    default=False,
    is_flag=True,
    required=False,
    help="Skip granting execute privileges to the user for the QC utility schema in the target database",
)
@pass_configuration
def setup_profiling_tools(
    configuration: Configuration,
    connection_id: str,
    dry_run: bool,
    create_qc_schema: bool,
    yes: bool,
    skip_asking_credentials: bool,
    skip_granting_privileges: bool,
):
    db_user = None
    db_password = None
    if not skip_asking_credentials:
        db_user = input("Admin DB User?")
        db_password = getpass.getpass("Admin DB Password?")

    if not yes and not dry_run:
        confirm = input(
            f"Are you sure you want to setup the utility functions to be able to run the profile for connection {connection_id}? [yes/No]"
        )
        if confirm.lower() != "yes":
            click.echo("Exiting without any operation performed.")
            return
    project_qc_schema = run_setup_profiling_tools(
        connection_id, dry_run, create_qc_schema, db_user, db_password, skip_granting_privileges
    )
    if not dry_run:
        message = f"Project DB has been set up. Modified schema: {project_qc_schema}"
    else:
        message = (
            f"Project DB dry run completed, no changes applied. Modified schema would have been: {project_qc_schema}"
        )
    click.echo(message)


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


@ui.command("run", help="Run the browser application with default settings")
@click.option("-d", "--debug", is_flag=True, default=False)
def run(debug: bool):
    from testgen.ui.scripts import patch_streamlit
    configure_logging(
        level=logging.INFO,
        log_format="%(message)s",
    )

    status_code: int = -1
    logger = logging.getLogger("testgen")
    stderr: typing.TextIO = typing.cast(typing.TextIO, logs.LogPipe(logger, logging.INFO))
    stdout: typing.TextIO = typing.cast(typing.TextIO, logs.LogPipe(logger, logging.INFO))

    use_ssl = os.path.isfile(settings.SSL_CERT_FILE) and os.path.isfile(settings.SSL_KEY_FILE)

    patch_streamlit.patch(force=True)

    try:
        app_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui/app.py")
        status_code = subprocess.check_call(
            [  # noqa: S607
                "streamlit",
                "run",
                app_file,
                "--browser.gatherUsageStats=false",
                f"--server.sslCertFile={settings.SSL_CERT_FILE}" if use_ssl else "",
                f"--server.sslKeyFile={settings.SSL_KEY_FILE}" if use_ssl else "",
                "--",
                f"{'--debug' if debug else ''}",
            ],
            stdout=stdout,
            stderr=stderr,
        )
    except Exception:
        LOG.exception(f"Testgen UI exited with status code {status_code}")
        raise
    finally:
        if stderr:
            stderr.close()
        if stdout:
            stdout.close()


@ui.command("plugins", help="List installed application plugins")
def list_ui_plugins():
    installed_plugins = list(plugins.discover())

    click.echo(click.style(len(installed_plugins), fg="bright_magenta") + click.style(" plugins installed", bold=True))
    for plugin in installed_plugins:
        click.echo(click.style(" + ", fg="bright_green") + f"{plugin.package: <30}" + f"\tversion: {plugin.version}")


if __name__ == "__main__":
    cli()
