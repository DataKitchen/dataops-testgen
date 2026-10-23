"""The CLI runs the process setup and reports an incomplete configuration itself."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from testgen.__main__ import cli

pytestmark = pytest.mark.unit

_INCOMPLETE = (False, "TG_METADATA_DB_HOST is not set.")


@pytest.fixture
def incomplete_configuration():
    with (
        patch("testgen.common.process_setup.is_standalone_mode", return_value=False),
        patch("testgen.common.process_setup.configure_logging"),
        patch("testgen.common.process_setup.docker_service.check_basic_configuration", return_value=_INCOMPLETE),
    ):
        yield


def test_the_cli_reports_an_incomplete_configuration_and_exits(incomplete_configuration):
    result = CliRunner().invoke(cli, ["list-projects"])

    assert result.exit_code == 1
    assert "TG_METADATA_DB_HOST is not set." in result.output
    assert "There was an unexpected error" not in result.output


def test_standalone_setup_runs_with_an_incomplete_configuration(incomplete_configuration):
    """Standalone setup writes the configuration the check would look for."""
    result = CliRunner().invoke(cli, ["standalone-setup", "--help"])

    assert result.exit_code == 0
    assert "TG_METADATA_DB_HOST is not set." not in result.output
