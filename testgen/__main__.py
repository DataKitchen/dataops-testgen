# Silence streamlit's "missing ScriptRunContext" / "No runtime found" /
# "Session state does not function" warnings, which fire whenever streamlit-
# decorated code runs outside an active script run (our CLI, scheduler, server,
# and any import that touches @st.cache_data). Must run before the first
# streamlit-using import, so it sits at the top of the module.
#
# We replace ``set_log_level`` itself, after seeding it to "error". Streamlit's
# own ``_update_logger`` callback fires on config parse and would otherwise
# downgrade us back to "info"; the cap floors any later call at ERROR.
def _silence_streamlit_logs() -> None:
    import logging as _logging

    try:
        from streamlit import logger as _st_logger
    except ImportError:
        return

    _original = _st_logger.set_log_level
    _original("error")

    def _capped(level):
        if isinstance(level, str):
            try:
                level_num = getattr(_logging, level.upper())
            except AttributeError:
                _original(level)
                return
        else:
            level_num = level
        _original(max(level_num, _logging.ERROR))

    _st_logger.set_log_level = _capped


_silence_streamlit_logs()


import base64
import importlib
import logging
import os
import pathlib
import platform
import secrets
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib.metadata import version as pkg_version

import click
from click.core import Context

from testgen import settings
from testgen.commands.exec_job import exec_job
from testgen.commands.job_runner import submit_and_wait
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
from testgen.commands.run_quick_start import (
    run_monitor_increment,
    run_quick_start,
    run_quick_start_increment,
    run_with_job_execution,
)
from testgen.commands.run_test_metadata_exporter import run_test_metadata_exporter
from testgen.commands.run_upgrade_db_config import get_schema_revision, is_db_revision_up_to_date, run_upgrade_db_config
from testgen.commands.test_generation import run_monitor_generation, run_test_generation
from testgen.common import (
    configure_logging,
    display_service,
    docker_service,
    get_tg_db,
    get_tg_host,
    get_tg_schema,
    version_service,
)
from testgen.common.models import database_session, with_database_session
from testgen.common.models.settings import PersistedSetting
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.notifications.base import smtp_configured
from testgen.common.standalone_postgres import (
    STANDALONE_URI_ENV_VAR,
    get_server_uri,
    is_standalone_mode,
)
from testgen.common.standalone_postgres import (
    get_home_dir as get_testgen_home,
)
from testgen.common.standalone_postgres import (
    start_server as start_standalone_postgres,
)
from testgen.scheduler import run_scheduler
from testgen.utils import plugins

LOG = logging.getLogger("testgen")

APP_MODULES = ["ui", "scheduler", "server"]
VERSION_DATA = version_service.get_version()
CHILDREN_POLL_INTERVAL = 10


def _forward_signal_to_child(child: subprocess.Popen, signum: int) -> None:
    # On POSIX, forward the signal verbatim. On Windows, subprocess.send_signal
    # rejects everything except SIGTERM / CTRL_C_EVENT / CTRL_BREAK_EVENT, so
    # fall back to terminate() — equivalent to TerminateProcess().
    if sys.platform == "win32":
        child.terminate()
    else:
        child.send_signal(signum)

@dataclass
class Configuration:
    verbose: bool = field(default=False)


# This is just sugar - @pass_obj or @pass_context would work too.
pass_configuration = click.make_pass_decorator(Configuration)


class CliGroup(click.Group):
    def invoke(self, ctx: Context):
        try:
            super().invoke(ctx)
        except click.exceptions.UsageError:
            raise
        except Exception:
            LOG.exception("There was an unexpected error")
            sys.exit(1)

    def format_epilog(self, _ctx: Context, formatter: click.HelpFormatter) -> None:
        # Schema revision is a DB round-trip; defer until `--help` is actually
        # requested rather than evaluating at module-load for every CLI invocation.
        formatter.write_paragraph()
        formatter.write_text(f"Schema revision: {get_schema_revision()}")


@click.group(
    cls=CliGroup,
    help=f"""
    {VERSION_DATA.edition} {VERSION_DATA.current or ""}

    {f"New version available! {VERSION_DATA.latest}" if VERSION_DATA.latest != VERSION_DATA.current else ""}
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
    if is_standalone_mode():
        start_standalone_postgres()

    if verbose:
        configure_logging(level=logging.DEBUG)
    else:
        configure_logging(level=logging.INFO)

    ctx.obj = Configuration(verbose=verbose)
    if not is_standalone_mode() and ctx.invoked_subcommand != "standalone-setup":
        status_ok, message = docker_service.check_basic_configuration()
        if not status_ok:
            click.secho(message, fg="red")
            sys.exit(1)

    if (
        ctx.invoked_subcommand not in ["run-app", "ui", "setup-system-db", "upgrade-system-version", "quick-start", "standalone-setup"]
        and not is_db_revision_up_to_date()
    ):
        click.secho("The system database schema is outdated. Automatically running the following command:", fg="red")
        click.secho("testgen upgrade-system-version", fg="red")
        do_upgrade_system_version()
        click.secho("\nNow running the requested command...", fg="red")
    LOG.debug("Current Step: Main Program")


@cli.command("run-profile", help="Generates a new profile of the table group.")
@click.option(
    "-tg",
    "--table-group-id",
    required=True,
    type=click.STRING,
    help="ID of the table group to profile. Use a table_group_id shown in list-table-groups.",
)
@click.option("--no-wait", is_flag=True, default=False, help="Print job ID and exit without waiting.")
def run_profile(table_group_id: str, no_wait: bool):
    with database_session():
        project_code = TableGroup.get(table_group_id).project_code
    submit_and_wait("run-profile", {"table_group_id": str(table_group_id)}, project_code, no_wait)


@cli.command("run-test-generation", help="Generates or refreshes the tests for a table group.")
@click.option(
    "-t",
    "--test-suite-id",
    required=False,
    type=click.STRING,
    help="ID of the test suite to generate. Use a test_suite_id shown in list-test-suites.",
)
@click.option(
    "-tg",
    "--table-group-id",
    help="The identifier for the table group used during a profile run. Use a table_group_id shown in list-table-groups.",
    required=False,
    type=click.STRING,
)
@click.option(
    "-ts",
    "--test-suite-key",
    help="The identifier for a test suite. Use a test_suite_key shown in list-test-suites.",
    required=False,
    type=click.STRING,
)
@click.option(
    "-gs",
    "--generation-set",
    help="A defined subset of tests to generate for your purpose. Use a generation_set defined for your project.",
    required=False,
    default="Standard",
)
@click.option("--no-wait", is_flag=True, default=False, help="Print job ID and exit without waiting.")
def run_generation(test_suite_id: str | None = None, table_group_id: str | None = None, test_suite_key: str | None = None, generation_set: str | None = None, no_wait: bool = False):
    with database_session():
        # For backward compatibility
        if not test_suite_id:
            test_suites = TestSuite.select_minimal_where(
                TestSuite.table_groups_id == table_group_id,
                TestSuite.test_suite == test_suite_key,
            )
            if test_suites:
                test_suite_id = test_suites[0].id
        project_code = TestSuite.get(test_suite_id).project_code
    submit_and_wait("run-test-generation", {"test_suite_id": str(test_suite_id), "generation_set": generation_set}, project_code, no_wait)


@cli.command("run-monitor-generation", help="Generates or refreshes the monitors for a table group.")
@click.option(
    "-t",
    "--test-suite-id",
    required=True,
    type=click.STRING,
    help="ID of the monitor suite to generate",
)
@with_database_session
def generate_monitors(test_suite_id: str):
    click.echo(f"run-monitor-generation for suite: {test_suite_id}")
    run_monitor_generation(test_suite_id, ["Freshness_Trend", "Volume_Trend", "Schema_Drift"])


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
@click.option("--no-wait", is_flag=True, default=False, help="Print job ID and exit without waiting.")
def run_tests(test_suite_id: str | None = None, project_key: str | None = None, test_suite_key: str | None = None, no_wait: bool = False):
    with database_session():
        # For backward compatibility
        if not test_suite_id:
            test_suites = TestSuite.select_minimal_where(
                TestSuite.project_code == project_key,
                TestSuite.test_suite == test_suite_key,
            )
            if test_suites:
                test_suite_id = test_suites[0].id
        project_code = TestSuite.get(test_suite_id).project_code
    submit_and_wait("run-tests", {"test_suite_id": str(test_suite_id)}, project_code, no_wait)


@cli.command("run-monitors", help="Performs tests defined for a monitor suite.")
@click.option(
    "-t",
    "--test-suite-id",
    required=True,
    type=click.STRING,
    help="ID of the monitor suite to run.",
)
@click.option("--no-wait", is_flag=True, default=False, help="Print job ID and exit without waiting.")
def run_monitors(test_suite_id: str, no_wait: bool = False):
    with database_session():
        project_code = TestSuite.get(test_suite_id).project_code
    submit_and_wait("run-monitors", {"test_suite_id": str(test_suite_id)}, project_code, no_wait)


@cli.command("exec-job", hidden=True, help="Execute a queued job. Internal use by the scheduler.")
@click.argument("job_execution_id", type=click.UUID)
def exec_job_cmd(job_execution_id):
    exec_job(job_execution_id)


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
    time_delta = timedelta(days=-35) # before the first monitor iteration (~34 days back)
    table_group_id = "0ea85e17-acbe-47fe-8394-9970725ad37d"
    test_suite_id = "9df7489d-92b3-49f9-95ca-512160d7896f"

    click.echo(f"run-profile with table_group_id: {table_group_id}")
    run_with_job_execution("run-profile", now_date + time_delta, table_group_id=table_group_id)

    LOG.info(f"run-test-generation with test_suite_id: {test_suite_id}")
    with_database_session(run_test_generation)(test_suite_id, "Standard")

    run_with_job_execution("run-tests", now_date + time_delta, test_suite_id=test_suite_id)

    total_iterations = 3
    for iteration in range(1, total_iterations + 1):
        click.echo(f"Running iteration: {iteration} / {total_iterations}")
        run_date = now_date + timedelta(days=-10 * (total_iterations - iteration)) # 10 day increments
        run_quick_start_increment(iteration)
        run_with_job_execution("run-tests", run_date, test_suite_id=test_suite_id)

    monitor_iterations = 68  # ~5 weeks
    monitor_interval = timedelta(hours=12)
    monitor_test_suite_id = "823a1fef-9b6d-48d5-9d0f-2db9812cc318"
    # Round down to nearest 12-hour mark (12:00 AM or 12:00 PM UTC)
    now = datetime.now(UTC)
    nearest_12h_mark = now.replace(hour=12 if now.hour >= 12 else 0, minute=0, second=0, microsecond=0)
    monitor_run_date = nearest_12h_mark - monitor_interval * (monitor_iterations - 1)
    weekday_morning_count = 0
    for iteration in range(1, monitor_iterations + 1):
        click.echo(f"Running monitor iteration: {iteration} / {monitor_iterations}")
        if monitor_run_date.weekday() < 5 and monitor_run_date.hour < 12:
            weekday_morning_count += 1
        run_monitor_increment(monitor_run_date, iteration, weekday_morning_count)
        run_with_job_execution("run-monitors", monitor_run_date, test_suite_id=monitor_test_suite_id)
        monitor_run_date += monitor_interval

    click.echo("Quick start has successfully finished.")


@cli.command("standalone-setup", help="Set up TestGen for standalone use with embedded PostgreSQL (no Docker required).")
@click.option("--username", prompt="Admin username", default="admin", help="Username for the TestGen web UI.")
@click.option(
    "--password", prompt="Admin password", hide_input=True, confirmation_prompt=True,
    default="testgen", help="Password for the TestGen web UI.",
)
def setup_standalone(username: str, password: str):
    config_dir = get_testgen_home()
    config_path = config_dir / "config.env"

    if config_path.exists():
        if not click.confirm(f"Config already exists at {config_path}. Overwrite?"):
            click.echo("Aborted.")
            return

    # Generate secrets (same approach as dk-installer)
    def generate_secret(length: int = 12) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return "".join(secrets.choice(alphabet) for _ in range(length))

    jwt_key = base64.b64encode(secrets.token_bytes(32)).decode()
    decrypt_salt = generate_secret()
    decrypt_password = generate_secret()
    log_dir = str(config_dir / "log")

    config_dir.mkdir(parents=True, exist_ok=True)

    config_lines = [
        "# TestGen standalone configuration",
        "# Generated by: testgen standalone-setup",
        "",
        "# Standalone mode (embedded PostgreSQL)",
        "TG_STANDALONE_MODE=yes",
        "",
        "# UI credentials",
        f"TESTGEN_USERNAME={username}",
        f"TESTGEN_PASSWORD={password}",
        "",
        "# Encryption keys",
        f"TG_DECRYPT_SALT={decrypt_salt}",
        f"TG_DECRYPT_PASSWORD={decrypt_password}",
        f"TG_JWT_HASHING_KEY={jwt_key}",
        "",
        "# Logging",
        f"TESTGEN_LOG_FILE_PATH={log_dir}",
        "",
        "# Analytics",
        "TG_ANALYTICS=yes",
        "",
        "# Trust target database certificates (for SQL Server, etc.)",
        "TG_TARGET_DB_TRUST_SERVER_CERTIFICATE=yes",
        "TG_EXPORT_TO_OBSERVABILITY_VERIFY_SSL=no",
    ]

    # Persist caller-supplied runtime overrides (ports, TLS) so they apply to
    # subsequent `testgen run-app` invocations.
    persisted_env_vars = ("TG_UI_PORT", "TG_API_PORT", "SSL_CERT_FILE", "SSL_KEY_FILE")
    persisted_lines = [f"{name}={os.environ[name]}" for name in persisted_env_vars if os.environ.get(name)]
    if persisted_lines:
        config_lines.extend(["", "# Runtime overrides from installer", *persisted_lines])

    config_path.write_text("\n".join(config_lines) + "\n")
    click.echo(f"Config written to {config_path}")

    # Reload settings — the module was already evaluated at import time
    # before the config file existed.  Reloading re-reads the new file
    # and re-evaluates all module-level variables.
    importlib.reload(settings)

    # Patch Streamlit to support editable-install component resolution
    click.echo("Patching Streamlit...")
    from testgen.ui.scripts.patch_streamlit import patch as patch_streamlit
    patch_streamlit(dev=True)

    # Seed Streamlit's first-run credentials file so `run-app` doesn't block
    # on the interactive email prompt. We don't care about the value — just
    # that the file exists so Streamlit skips the prompt.
    streamlit_creds = pathlib.Path.home() / ".streamlit" / "credentials.toml"
    if not streamlit_creds.exists():
        streamlit_creds.parent.mkdir(parents=True, exist_ok=True)
        streamlit_creds.write_text('[general]\nemail = ""\n')

    # Start embedded PostgreSQL (standalone mode is now active via config)
    start_standalone_postgres()

    # Initialize the database
    click.echo("Initializing database...")
    run_launch_db_config(delete_db=False)

    # Send analytics event for pip install tracking
    try:
        from testgen.common.mixpanel_service import MixpanelService

        mp = MixpanelService()
        mp.send_event(
            "standalone_setup",
            username=username,
            install_type="standalone",
            version=pkg_version("dataops-testgen"),
            python_info=f"{platform.python_implementation()} {platform.python_version()}",
            **{"$os": platform.system()},
            os_version=platform.release(),
            os_arch=platform.machine(),
        )
    except Exception:  # noqa: S110
        pass

    click.echo("")
    click.echo(click.style("TestGen is ready!", fg="green", bold=True))
    click.echo("")
    click.echo("  To load demo data (optional):")
    click.echo("    testgen quick-start")
    click.echo("")
    click.echo("  Start the application:")
    click.echo("    testgen run-app")
    click.echo("")
    click.echo("  Then open http://localhost:8501 in your browser.")
    click.echo(f"  Log in with username: {username}")


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

    use_ssl = settings.UI_TLS_ENABLED

    if settings.IS_DEBUG:
        patch_streamlit.patch(dev=True)

    @with_database_session
    def init_ui():
        PersistedSetting.set("SMTP_CONFIGURED", smtp_configured())

    init_ui()

    app_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui/app.py")

    # In standalone mode, pass the pgserver URI to the Streamlit subprocess
    # so it can connect without acquiring the pgserver file lock.
    child_env = {**os.environ, "TG_JOB_SOURCE": "UI"}
    if is_standalone_mode():
        server_uri = get_server_uri()
        if server_uri:
            child_env = {**os.environ, "TG_JOB_SOURCE": "UI", STANDALONE_URI_ENV_VAR: server_uri}

    process= subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            app_file,
            "--browser.gatherUsageStats=false",
            f"--logger.level={'debug' if settings.IS_DEBUG else 'error'}",
            "--client.showErrorDetails=none",
            "--client.toolbarMode=minimal",
            "--server.enableStaticServing=true",
            f"--server.port={settings.UI_PORT}",
            f"--server.sslCertFile={settings.SSL_CERT_FILE}" if use_ssl else "",
            f"--server.sslKeyFile={settings.SSL_KEY_FILE}" if use_ssl else "",
            "--",
            f"{'--debug' if settings.IS_DEBUG else ''}",
        ],
        env=child_env,
    )
    def term_ui(signum, _):
        LOG.info(f"Sending termination signal {signum} to Testgen UI")
        _forward_signal_to_child(process, signum)
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

        case "server":
            from testgen.server import run_server
            run_server()

        case "all":
            children = [
                subprocess.Popen([sys.executable, "-m", "testgen", "run-app", m], start_new_session=True)
                for m in APP_MODULES
            ]

            def term_children(signum, _):
                for child in children:
                    _forward_signal_to_child(child, signum)

            signal.signal(signal.SIGINT, term_children)
            signal.signal(signal.SIGTERM, term_children)

            terminating = False
            while children:
                try:
                    children[0].wait(CHILDREN_POLL_INTERVAL)
                except subprocess.TimeoutExpired:
                    pass

                for child in children:
                    if child.poll() is not None:
                        children.remove(child)
                        if not terminating:
                            terminating = True
                            term_children(signal.SIGTERM, None)



if __name__ == "__main__":
    cli()
