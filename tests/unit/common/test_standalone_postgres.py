"""Unit tests for starting embedded PostgreSQL in standalone mode."""

import logging
import subprocess
import sys
from unittest import mock

import pytest

from testgen.common import standalone_postgres


@pytest.fixture
def fake_pgserver():
    """Mock the ``pixeltable_pgserver`` module imported inside ``start_server``."""
    fake = mock.MagicMock()
    fake.get_server.return_value.get_uri.return_value = "postgresql:///db?host=/tmp/sock"
    with mock.patch.dict(sys.modules, {"pixeltable_pgserver": fake}):
        yield fake


@pytest.fixture(autouse=True)
def reset_module_state():
    """Isolate the module-level server singleton and skip real ORM/atexit side effects."""
    standalone_postgres._server = None
    with (
        mock.patch.object(standalone_postgres, "_reinitialize_orm_engine"),
        mock.patch("atexit.register"),
    ):
        yield
    standalone_postgres._server = None


def test_fresh_data_dir_uses_new_install_version(fake_pgserver, tmp_path):
    fake_pgserver.pgdata_version.return_value = None

    standalone_postgres.start_server(tmp_path / "pgdata")

    assert fake_pgserver.get_server.call_args.kwargs["postgres_version"] == (
        standalone_postgres.NEW_INSTALL_POSTGRES_VERSION
    )


def test_new_install_version_is_16():
    # The bundled PostgreSQL 18 Windows build needs a MinGW runtime it does not ship,
    # so a fresh cluster must be initialized on 16.
    assert standalone_postgres.NEW_INSTALL_POSTGRES_VERSION == 16


@pytest.mark.parametrize("on_disk_version", [16, 18])
def test_existing_data_dir_honors_on_disk_version(fake_pgserver, tmp_path, on_disk_version):
    # A cluster keeps running on the major that initialized it, whichever that was.
    fake_pgserver.pgdata_version.return_value = on_disk_version

    standalone_postgres.start_server(tmp_path / "pgdata")

    assert fake_pgserver.get_server.call_args.kwargs["postgres_version"] == on_disk_version


def _fail_like_pgserver(stderr: str):
    """Log a failed command the way pgserver does, then raise its bare CalledProcessError."""

    def get_server(*_args, **_kwargs):
        logging.getLogger("pixeltable_pgserver").error(
            "Failed postgres command %s:\nstdout:\n%s\n---\nstderr:\n%s\n---\n", ("initdb",), "", stderr
        )
        raise subprocess.CalledProcessError(1, ("initdb",))

    return get_server


def test_a_refusal_to_run_elevated_explains_what_to_do(fake_pgserver, tmp_path):
    fake_pgserver.pgdata_version.return_value = None
    fake_pgserver.get_server.side_effect = _fail_like_pgserver(
        "Execution of PostgreSQL by a user with administrative permissions is not\npermitted."
    )

    with pytest.raises(standalone_postgres.EmbeddedPostgresError) as raised:
        standalone_postgres.start_server(tmp_path / "pgdata")

    assert standalone_postgres.ELEVATED_PROCESS_HINT in str(raised.value)


def test_any_other_start_failure_carries_the_postgres_output(fake_pgserver, tmp_path):
    fake_pgserver.pgdata_version.return_value = None
    fake_pgserver.get_server.side_effect = _fail_like_pgserver('program "postgres" is needed by initdb')

    with pytest.raises(standalone_postgres.EmbeddedPostgresError) as raised:
        standalone_postgres.start_server(tmp_path / "pgdata")

    assert 'program "postgres" is needed by initdb' in str(raised.value)
    assert standalone_postgres.ELEVATED_PROCESS_HINT not in str(raised.value)
    assert standalone_postgres._server is None


def test_the_error_capture_is_removed_after_starting(fake_pgserver, tmp_path):
    fake_pgserver.pgdata_version.return_value = None
    pgserver_logger = logging.getLogger("pixeltable_pgserver")
    handlers_before = list(pgserver_logger.handlers)

    standalone_postgres.start_server(tmp_path / "pgdata")

    assert pgserver_logger.handlers == handlers_before


def _fail_starting_like_pgserver(data_dir, new_log_lines: str, error: subprocess.SubprocessError):
    """Append to the server log as pg_ctl does, log all of it the way pgserver does, then raise *error*."""

    def get_server(*_args, **_kwargs):
        server_log = data_dir / standalone_postgres.SERVER_LOG_NAME
        with server_log.open("a") as log_file:
            log_file.write(new_log_lines)
        logging.getLogger("pixeltable_pgserver").error(
            f"Failed to start server.\nShowing contents of postgres server log ({server_log}) below:\n"
            f"{server_log.read_text()}"
        )
        raise error

    return get_server


def test_a_start_timeout_is_reported_with_the_server_log(fake_pgserver, tmp_path):
    data_dir = tmp_path / "pgdata"
    data_dir.mkdir()
    fake_pgserver.pgdata_version.return_value = None
    fake_pgserver.get_server.side_effect = _fail_starting_like_pgserver(
        data_dir, "FATAL: lock file\n", subprocess.TimeoutExpired(("pg_ctl",), 10)
    )
    pgserver_logger = logging.getLogger("pixeltable_pgserver")
    handlers_before = list(pgserver_logger.handlers)

    with pytest.raises(standalone_postgres.EmbeddedPostgresError, match="FATAL: lock file"):
        standalone_postgres.start_server(data_dir)

    assert pgserver_logger.handlers == handlers_before


def test_a_failed_start_reports_only_the_server_log_it_wrote(fake_pgserver, tmp_path):
    """The server log is never truncated, so earlier starts would bury the cause and could add a stale hint."""
    data_dir = tmp_path / "pgdata"
    data_dir.mkdir()
    earlier_starts = "LOG:  database system is ready to accept connections\n" * 500
    stale_refusal = "Execution of PostgreSQL by a user with administrative permissions is not\npermitted.\n"
    (data_dir / standalone_postgres.SERVER_LOG_NAME).write_text(earlier_starts + stale_refusal)
    fake_pgserver.pgdata_version.return_value = None
    fake_pgserver.get_server.side_effect = _fail_starting_like_pgserver(
        data_dir,
        'FATAL:  invalid value for parameter "port": "notanumber"\n',
        subprocess.CalledProcessError(1, ("pg_ctl",)),
    )

    with pytest.raises(standalone_postgres.EmbeddedPostgresError) as raised:
        standalone_postgres.start_server(data_dir)

    message = str(raised.value)
    assert 'invalid value for parameter "port"' in message
    assert "ready to accept connections" not in message
    assert standalone_postgres.ELEVATED_PROCESS_HINT not in message


def test_a_refusal_written_by_this_start_explains_what_to_do(fake_pgserver, tmp_path):
    """Starting an existing cluster elevated reports the refusal only in the server log."""
    data_dir = tmp_path / "pgdata"
    data_dir.mkdir()
    (data_dir / standalone_postgres.SERVER_LOG_NAME).write_text("LOG:  database system is shut down\n")
    fake_pgserver.pgdata_version.return_value = 16
    fake_pgserver.get_server.side_effect = _fail_starting_like_pgserver(
        data_dir,
        "Execution of PostgreSQL by a user with administrative permissions is not\npermitted.\n",
        subprocess.CalledProcessError(1, ("pg_ctl",)),
    )

    with pytest.raises(standalone_postgres.EmbeddedPostgresError) as raised:
        standalone_postgres.start_server(data_dir)

    assert standalone_postgres.ELEVATED_PROCESS_HINT in str(raised.value)
    assert "database system is shut down" not in str(raised.value)


def test_a_failure_pgserver_did_not_log_carries_the_command_error(fake_pgserver, tmp_path):
    fake_pgserver.pgdata_version.return_value = None
    fake_pgserver.get_server.side_effect = subprocess.CalledProcessError(
        9, ["useradd", "pgserver"], stderr="useradd: cannot lock /etc/passwd"
    )

    with pytest.raises(standalone_postgres.EmbeddedPostgresError) as raised:
        standalone_postgres.start_server(tmp_path / "pgdata")

    assert "useradd" in str(raised.value)
    assert "cannot lock /etc/passwd" in str(raised.value)


@pytest.fixture
def fake_psutil():
    fake = mock.MagicMock()
    fake.pid_exists.side_effect = lambda pid: pid == 4242
    with mock.patch.dict(sys.modules, {"psutil": fake}):
        yield fake


@pytest.mark.parametrize(
    ("handles", "expected"),
    [
        (None, False), ("", False), ("[]", False), ("[1111]", False), ("[1111, 4242]", True),
        ("not json", False), ('{"pid": 4242}', False),
    ],
    ids=[
        "no handle file", "empty file", "no handles", "only a dead process", "a live process",
        "unreadable file", "not a list",
    ],
)
def test_server_in_use_counts_only_live_handles(fake_psutil, tmp_path, handles, expected):
    """A process that dies without exiting cleanly stays listed, so a listed PID counts only while it is alive."""
    if handles is not None:
        (tmp_path / ".handle_pids.json").write_text(handles)

    assert standalone_postgres.is_server_in_use(tmp_path) is expected


def test_server_in_use_is_false_without_psutil(tmp_path):
    (tmp_path / ".handle_pids.json").write_text("[4242]")

    with mock.patch.dict(sys.modules, {"psutil": None}):
        assert standalone_postgres.is_server_in_use(tmp_path) is False
