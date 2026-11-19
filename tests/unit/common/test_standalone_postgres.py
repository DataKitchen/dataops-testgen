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


def test_a_start_timeout_is_reported_with_the_server_log(fake_pgserver, tmp_path):
    fake_pgserver.pgdata_version.return_value = None
    pgserver_logger = logging.getLogger("pixeltable_pgserver")
    handlers_before = list(pgserver_logger.handlers)

    def get_server(*_args, **_kwargs):
        pgserver_logger.error("Failed to start server.\nShowing contents of postgres server log:\nFATAL: lock file")
        raise subprocess.TimeoutExpired(("pg_ctl",), 10)

    fake_pgserver.get_server.side_effect = get_server

    with pytest.raises(standalone_postgres.EmbeddedPostgresError, match="FATAL: lock file"):
        standalone_postgres.start_server(tmp_path / "pgdata")

    assert pgserver_logger.handlers == handlers_before


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


def test_the_elevation_hint_keeps_the_postgres_output(fake_pgserver, tmp_path):
    """The server log spans earlier attempts, so a stale refusal must not hide the current cause."""
    fake_pgserver.pgdata_version.return_value = None
    fake_pgserver.get_server.side_effect = _fail_like_pgserver(
        "Execution of PostgreSQL by a user with administrative permissions is not\npermitted.\n"
        'FATAL:  invalid value for parameter "port": "notanumber"'
    )

    with pytest.raises(standalone_postgres.EmbeddedPostgresError) as raised:
        standalone_postgres.start_server(tmp_path / "pgdata")

    assert standalone_postgres.ELEVATED_PROCESS_HINT in str(raised.value)
    assert 'invalid value for parameter "port"' in str(raised.value)


def test_server_in_use_is_false_without_psutil(tmp_path):
    (tmp_path / ".handle_pids.json").write_text("[4242]")

    with mock.patch.dict(sys.modules, {"psutil": None}):
        assert standalone_postgres.is_server_in_use(tmp_path) is False
