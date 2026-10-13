from unittest.mock import patch

import pytest

from testgen.commands.run_upgrade_db_config import _refresh_static_metadata

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_upgrade_db_config"
PARAMS = {"SCHEMA_NAME": "tgapp", "TESTGEN_ADMIN_USER": "tg_admin", "TESTGEN_ADMIN_PASSWORD": "secret"}


def _executed_statements(app_user: str) -> list[list[str]]:
    with (
        patch(f"{MODULE}.settings.DATABASE_USER", app_user),
        patch(f"{MODULE}.read_template_sql_file", side_effect=lambda name, _directory: name),
        patch(f"{MODULE}.replace_params", side_effect=lambda query, _params: query),
        patch(f"{MODULE}.import_metadata_records_from_yaml"),
        patch(f"{MODULE}.execute_db_queries") as execute,
    ):
        _refresh_static_metadata(PARAMS)
    return [[query for query, _ in call.args[0]] for call in execute.call_args_list]


def test_every_upgrade_grants_a_separate_app_user_access_after_recreating_objects():
    batches = _executed_statements("tg_app")

    assert batches[0] == ["050_populate_new_schema_metadata.sql", "060_create_standard_views.sql"]
    assert batches[1] == ["055_recreate_metadata_constraints.sql"]
    grants = batches[-1]
    assert len(batches) == 3
    assert 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA tgapp TO "tg_app"' in grants
    assert any(statement.startswith("ALTER DEFAULT PRIVILEGES") for statement in grants)


def test_an_upgrade_with_one_database_user_grants_nothing():
    assert len(_executed_statements("tg_admin")) == 2
