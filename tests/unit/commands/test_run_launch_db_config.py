from unittest.mock import patch

import pytest

from testgen.commands.run_launch_db_config import _ensure_app_user_exists, _get_app_user_grants

pytestmark = pytest.mark.unit


def test_no_grants_when_the_app_user_is_the_admin_user():
    assert _get_app_user_grants("tgapp", "testgen", "testgen") == []


def test_no_grants_without_an_app_user():
    assert _get_app_user_grants("tgapp", "testgen", None) == []


def test_grants_cover_existing_and_future_objects_for_a_separate_app_user():
    statements = _get_app_user_grants("tgapp", "tg_admin", "tg_app")

    assert 'GRANT USAGE ON SCHEMA tgapp TO "tg_app"' in statements
    assert 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA tgapp TO "tg_app"' in statements
    assert (
        'ALTER DEFAULT PRIVILEGES IN SCHEMA tgapp GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "tg_app"'
        in statements
    )
    assert not any("CREATE" in statement or "ALL PRIVILEGES" in statement for statement in statements)


def test_app_user_name_is_quoted_as_an_identifier():
    statements = _get_app_user_grants("tgapp", "tg_admin", 'App"User')

    assert all(statement.endswith('TO "App""User"') for statement in statements)


def test_missing_app_user_is_reported_before_setup_starts():
    params = {"TESTGEN_ADMIN_USER": "tg_admin", "TESTGEN_ADMIN_PASSWORD": "secret"}

    with (
        patch("testgen.commands.run_launch_db_config.execute_db_queries", return_value=([0], [1])),
        pytest.raises(ValueError, match="'tg_app' set in TG_METADATA_DB_USER does not exist"),
    ):
        _ensure_app_user_exists("tg_app", params)


def test_existing_app_user_passes_the_check():
    params = {"TESTGEN_ADMIN_USER": "tg_admin", "TESTGEN_ADMIN_PASSWORD": "secret"}

    with patch("testgen.commands.run_launch_db_config.execute_db_queries", return_value=([1], [1])):
        _ensure_app_user_exists("tg_app", params)
