"""standalone-setup over an existing configuration, and when embedded PostgreSQL cannot start."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from testgen.__main__ import cli
from testgen.common.standalone_postgres import EmbeddedPostgresError

pytestmark = pytest.mark.unit

MODULE = "testgen.__main__"
ARGS = ["standalone-setup", "--username", "admin", "--password", "secret"]


@pytest.fixture
def setup_steps(tmp_path, monkeypatch):
    """Point TestGen's home at a temporary folder and stub every step that needs a real database."""
    home = tmp_path / ".testgen"
    monkeypatch.setenv("TG_TESTGEN_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    with (
        patch("testgen.common.process_setup.is_standalone_mode", return_value=False),
        patch("testgen.common.process_setup.configure_logging"),
        patch(f"{MODULE}.importlib.reload"),
        patch("testgen.ui.scripts.patch_streamlit.patch"),
        patch(f"{MODULE}.start_standalone_postgres") as start,
        patch(f"{MODULE}.run_launch_db_config") as launch_db,
        patch(f"{MODULE}.is_server_running", return_value=False) as running,
        patch("testgen.common.mixpanel_service.MixpanelService"),
    ):
        yield {"home": home, "start": start, "launch_db": launch_db, "running": running}


def test_a_fresh_setup_writes_the_config_and_creates_the_database(setup_steps):
    result = CliRunner().invoke(cli, ARGS)

    assert result.exit_code == 0, result.output
    assert (setup_steps["home"] / "config.env").is_file()
    setup_steps["launch_db"].assert_called_once_with(delete_db=False)


def test_an_existing_config_without_a_terminal_fails_with_directions(setup_steps):
    """An installer runs setup with no terminal, so it cannot answer the overwrite prompt."""
    setup_steps["home"].mkdir()
    (setup_steps["home"] / "config.env").write_text("TG_STANDALONE_MODE=yes\n")

    result = CliRunner().invoke(cli, ARGS)

    assert result.exit_code == 1
    assert "Config already exists" in result.stderr
    assert f"delete {setup_steps['home']}" in result.stderr
    assert (setup_steps["home"] / "config.env").read_text() == "TG_STANDALONE_MODE=yes\n"
    setup_steps["start"].assert_not_called()
    setup_steps["launch_db"].assert_not_called()


def test_overwriting_an_existing_config_resets_the_database(setup_steps):
    setup_steps["home"].mkdir()
    (setup_steps["home"] / "config.env").write_text("TG_STANDALONE_MODE=yes\n")

    with patch(f"{MODULE}._can_prompt", return_value=True):
        result = CliRunner().invoke(cli, ARGS, input="y\n")

    assert result.exit_code == 0, result.output
    assert "erase the existing TestGen data" in result.output
    setup_steps["launch_db"].assert_called_once_with(delete_db=True)


def test_overwriting_while_testgen_is_running_is_refused(setup_steps):
    """Dropping the database under a running app leaves it holding keys that no longer match."""
    setup_steps["home"].mkdir()
    (setup_steps["home"] / "config.env").write_text("TG_STANDALONE_MODE=yes\n")
    setup_steps["running"].return_value = True

    with patch(f"{MODULE}._can_prompt", return_value=True):
        result = CliRunner().invoke(cli, ARGS, input="y\n")

    assert result.exit_code == 1
    assert "Stop TestGen, then run this command again." in result.stderr
    assert (setup_steps["home"] / "config.env").read_text() == "TG_STANDALONE_MODE=yes\n"
    setup_steps["launch_db"].assert_not_called()


def test_declining_the_overwrite_changes_nothing(setup_steps):
    setup_steps["home"].mkdir()
    (setup_steps["home"] / "config.env").write_text("TG_STANDALONE_MODE=yes\n")

    with patch(f"{MODULE}._can_prompt", return_value=True):
        result = CliRunner().invoke(cli, ARGS, input="n\n")

    assert result.exit_code == 0
    assert (setup_steps["home"] / "config.env").read_text() == "TG_STANDALONE_MODE=yes\n"
    setup_steps["start"].assert_not_called()


def test_an_existing_standalone_config_does_not_start_the_database_before_setup(setup_steps):
    """Setup decides whether to overwrite before anything touches the embedded database."""
    setup_steps["home"].mkdir()
    (setup_steps["home"] / "config.env").write_text("TG_STANDALONE_MODE=yes\n")

    with (
        patch("testgen.common.process_setup.is_standalone_mode", return_value=True),
        patch("testgen.common.process_setup.start_server") as group_start,
    ):
        CliRunner().invoke(cli, ARGS)

    group_start.assert_not_called()


def test_a_database_that_cannot_start_is_reported_without_a_traceback(setup_steps):
    setup_steps["start"].side_effect = EmbeddedPostgresError("Embedded PostgreSQL could not start. Run it elsewhere.")

    result = CliRunner().invoke(cli, ARGS)

    assert result.exit_code == 1
    assert "Embedded PostgreSQL could not start. Run it elsewhere." in result.stderr
    assert "Traceback" not in result.output
    setup_steps["launch_db"].assert_not_called()
