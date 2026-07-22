"""Unit tests for embedded-PostgreSQL version selection in standalone mode."""

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


def test_existing_data_dir_honors_on_disk_version(fake_pgserver, tmp_path):
    # A cluster initialized by an older bundled major must keep running on it.
    fake_pgserver.pgdata_version.return_value = 16

    standalone_postgres.start_server(tmp_path / "pgdata")

    assert fake_pgserver.get_server.call_args.kwargs["postgres_version"] == 16
