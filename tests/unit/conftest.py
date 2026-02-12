from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def patched_settings():
    settings = {
        "BASE_URL": "http://tg-base-url",
    }
    with patch("testgen.common.models.settings.PersistedSetting.get") as mock:
        mock.side_effect = settings.get
        yield mock


@pytest.fixture
def db_session_mock():
    with patch("testgen.common.models.Session") as factory_mock:
        yield factory_mock().__enter__()
