# Importing the fixtures registers them for this test subtree (autouse flags preserved).
import pytest

from testgen.common.database.flavor import duckdb_flavor_service
from testgen.testing.fixtures import db_session_mock, patched_settings  # noqa: F401


@pytest.fixture(autouse=True)
def spill_root(tmp_path, monkeypatch):
    """Keep every spill and every sweep inside tmp_path.

    ``init()`` creates ``TEMP_DIRECTORY`` on any connection it opens and ``exec_job`` sweeps it,
    and the real one is shared with whatever TestGen is running on the same machine.
    """
    root = tmp_path / "spill"
    monkeypatch.setattr(duckdb_flavor_service, "TEMP_DIRECTORY", root)
    return root
