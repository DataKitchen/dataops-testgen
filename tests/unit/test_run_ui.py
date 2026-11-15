import pathlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from streamlit.web.server.app_discovery import discover_asgi_app

from testgen import settings
from testgen.__main__ import run_ui

pytestmark = pytest.mark.unit

MODULE = "testgen.__main__"
PATCH_MODULE = "testgen.ui.scripts.patch_streamlit"


def _run_ui(
    monkeypatch, debug: bool, patch_index_error: Exception | None = None
) -> tuple[MagicMock, MagicMock, MagicMock]:
    monkeypatch.setattr(settings, "IS_DEBUG", debug)
    process = MagicMock()
    process.wait.return_value = 0
    with (
        patch(f"{MODULE}.subprocess.Popen", return_value=process) as popen,
        patch(f"{MODULE}._subprocess_spawn_kwargs", return_value={}),
        patch(f"{MODULE}._install_shutdown_handler"),
        patch(f"{MODULE}.with_database_session", side_effect=lambda fn: fn),
        patch(f"{MODULE}.log_smtp_configuration_problems"),
        patch(f"{MODULE}.smtp_configured", return_value=False),
        patch(f"{MODULE}.PersistedSetting"),
        patch(f"{MODULE}.is_standalone_mode", return_value=False),
        patch(f"{PATCH_MODULE}.patch") as full_patch,
        patch(f"{PATCH_MODULE}.patch_index", side_effect=patch_index_error) as patch_index,
    ):
        run_ui()
    return popen, full_patch, patch_index


def test_ui_launches_a_script_streamlit_runs_as_an_app(monkeypatch):
    popen, _, _ = _run_ui(monkeypatch, debug=False)

    args = popen.call_args.args[0]
    script = pathlib.Path(args[args.index("run") + 1])
    assert discover_asgi_app(script).is_asgi_app


def test_ui_rebuilds_the_index_on_every_start(monkeypatch):
    _, full_patch, patch_index = _run_ui(monkeypatch, debug=False)

    patch_index.assert_called_once_with()
    full_patch.assert_not_called()


def test_ui_in_debug_mode_applies_every_patch(monkeypatch):
    _, full_patch, patch_index = _run_ui(monkeypatch, debug=True)

    full_patch.assert_called_once_with(dev=True)
    patch_index.assert_not_called()


def test_ui_starts_when_the_index_cannot_be_written(monkeypatch, caplog):
    popen, _, _ = _run_ui(monkeypatch, debug=False, patch_index_error=PermissionError("read-only file system"))

    popen.assert_called_once()
    assert "read-only file system" in caplog.text


def test_app_loads_no_custom_component_before_its_first_script_run():
    loaded = subprocess.run(
        [sys.executable, "-c", "import sys, testgen.ui.asgi; print(sorted(sys.modules))"],  # noqa: S603
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "extra_streamlit_components" not in loaded
