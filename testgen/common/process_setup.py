"""Setup a TestGen process does before its work."""

import logging
import os

from testgen.common import docker_service
from testgen.common.logs import configure_logging
from testgen.common.standalone_postgres import (
    STANDALONE_URI_ENV_VAR,
    ensure_standalone_setup,
    is_standalone_mode,
    start_server,
)


class ConfigurationError(Exception):
    """The settings TestGen needs to reach its metadata database are incomplete."""


def setup_process(*, verbose: bool = False, check_configuration: bool = True) -> None:
    """Attach to the metadata database, configure logging, and check the configuration.

    :param verbose: Log at DEBUG rather than INFO.
    :param check_configuration: Check the metadata database settings. Standalone mode needs none,
        so the check is skipped there either way.
    :raises ConfigurationError: A metadata database setting is missing.
    """
    standalone = is_standalone_mode()
    if standalone:
        # A process that inherits the server URI must attach rather than start the server: each
        # start registers the calling PID in pgserver's on-disk handle list, and any PID left
        # over after a hard kill prevents the parent from actually stopping postgres.
        if inherited_uri := os.environ.get(STANDALONE_URI_ENV_VAR):
            ensure_standalone_setup(inherited_uri)
        else:
            start_server()

    configure_logging(level=logging.DEBUG if verbose else logging.INFO)

    if check_configuration and not standalone:
        status_ok, message = docker_service.check_basic_configuration()
        if not status_ok:
            raise ConfigurationError(message)
