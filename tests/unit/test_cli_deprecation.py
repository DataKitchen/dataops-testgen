"""Every CLI command warns as deprecated unless it is in the system set.

The default is "deprecated", so a command added later warns without anyone remembering to
mark it. These pin the two things that can go wrong: a system command warning anyway, and
the system set naming something that is no longer a command.
"""

import pytest
from click.testing import CliRunner

from testgen.__main__ import SYSTEM_COMMANDS, cli

_DEPRECATION_TEXT = "is deprecated. Use the TestGen API or MCP server instead."


@pytest.mark.unit
def test_system_commands_all_exist() -> None:
    """A stale name in the system set would silently exempt nothing."""
    assert SYSTEM_COMMANDS <= set(cli.commands)


@pytest.mark.unit
@pytest.mark.parametrize("command", sorted(SYSTEM_COMMANDS))
def test_system_command_does_not_warn(command: str) -> None:
    result = CliRunner().invoke(cli, [command, "--help"])

    assert _DEPRECATION_TEXT not in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("command", sorted(set(cli.commands) - SYSTEM_COMMANDS))
def test_every_other_command_warns(command: str) -> None:
    result = CliRunner().invoke(cli, [command, "--help"])

    assert f"`testgen {command}` {_DEPRECATION_TEXT}" in result.stderr


@pytest.mark.unit
def test_warning_goes_to_stderr_only() -> None:
    """A command's output is piped and parsed; the notice must not land in it."""
    result = CliRunner().invoke(cli, ["list-projects", "--help"])

    assert _DEPRECATION_TEXT not in result.stdout


@pytest.mark.unit
def test_bare_invocation_does_not_warn() -> None:
    """``testgen`` with no command resolves no subcommand, so there is nothing to name."""
    result = CliRunner().invoke(cli, [])

    assert _DEPRECATION_TEXT not in result.stderr
