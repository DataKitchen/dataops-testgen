from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _patch_cli_startup():
    """Prevent the CLI group callback from checking DB config or schema revision."""
    with patch(
        "testgen.common.docker_service.check_basic_configuration",
        return_value=(True, ""),
    ), patch(
        "testgen.__main__.is_db_revision_up_to_date",
        return_value=True,
    ):
        yield
