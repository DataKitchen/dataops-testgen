import logging
from unittest.mock import Mock, call, patch

import pytest

from testgen.common.process_setup import ConfigurationError, setup_process
from testgen.common.standalone_postgres import STANDALONE_URI_ENV_VAR

pytestmark = pytest.mark.unit

MODULE = "testgen.common.process_setup"


@pytest.fixture
def setup_parts():
    """The setup steps, as children of one mock so their order can be asserted."""
    steps = Mock()
    steps.check.return_value = (True, "")
    with (
        patch(f"{MODULE}.is_standalone_mode", return_value=False) as standalone,
        patch(f"{MODULE}.ensure_standalone_setup", steps.attach),
        patch(f"{MODULE}.start_server", steps.start),
        patch(f"{MODULE}.configure_logging", steps.logging),
        patch(f"{MODULE}.docker_service.check_basic_configuration", steps.check),
    ):
        yield {
            "standalone": standalone, "attach": steps.attach, "start": steps.start, "logging": steps.logging,
            "check": steps.check, "steps": steps,
        }


def test_a_standalone_child_attaches_to_the_server_its_parent_started(setup_parts, monkeypatch):
    """Starting a second server registers this process with pgserver, which keeps the parent's
    server from ever stopping once this process is killed."""
    setup_parts["standalone"].return_value = True
    monkeypatch.setenv(STANDALONE_URI_ENV_VAR, "postgresql://postgres:@/postgres?host=/tmp/pgdata")

    setup_process()

    setup_parts["attach"].assert_called_once_with("postgresql://postgres:@/postgres?host=/tmp/pgdata")
    setup_parts["start"].assert_not_called()


def test_a_standalone_process_with_no_parent_server_starts_one(setup_parts, monkeypatch):
    setup_parts["standalone"].return_value = True
    monkeypatch.delenv(STANDALONE_URI_ENV_VAR, raising=False)

    setup_process()

    setup_parts["start"].assert_called_once_with()
    setup_parts["attach"].assert_not_called()


def test_standalone_mode_skips_the_configuration_check(setup_parts, monkeypatch):
    """Standalone mode reaches its metadata database without any of the settings checked."""
    setup_parts["standalone"].return_value = True
    monkeypatch.setenv(STANDALONE_URI_ENV_VAR, "postgresql://postgres:@/postgres")

    setup_process()

    setup_parts["check"].assert_not_called()


def test_an_incomplete_configuration_is_raised(setup_parts):
    setup_parts["check"].return_value = (False, "TG_METADATA_DB_HOST is not set.")

    with pytest.raises(ConfigurationError, match="TG_METADATA_DB_HOST"):
        setup_process()


def test_the_configuration_check_can_be_skipped(setup_parts):
    setup_parts["check"].return_value = (False, "TG_METADATA_DB_HOST is not set.")

    setup_process(check_configuration=False)

    setup_parts["check"].assert_not_called()


@pytest.mark.parametrize(("verbose", "level"), [(False, logging.INFO), (True, logging.DEBUG)])
def test_logging_follows_verbosity(setup_parts, verbose, level):
    setup_process(verbose=verbose)

    setup_parts["logging"].assert_called_once_with(level=level)


def test_in_standalone_mode_the_server_is_reached_before_logging(setup_parts, monkeypatch):
    setup_parts["standalone"].return_value = True
    monkeypatch.delenv(STANDALONE_URI_ENV_VAR, raising=False)

    setup_process(check_configuration=True)

    assert setup_parts["steps"].mock_calls == [call.start(), call.logging(level=logging.INFO)]


def test_outside_standalone_mode_logging_is_set_up_before_the_check(setup_parts):
    setup_process()

    assert setup_parts["steps"].mock_calls == [call.logging(level=logging.INFO), call.check()]
