from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def patched_settings():
    with patch("testgen.settings.UI_BASE_URL", "http://tg-base-url"):
        yield


@pytest.fixture
def db_session_mock():
    with patch("testgen.common.models.Session") as factory_mock:
        yield factory_mock().__enter__()
