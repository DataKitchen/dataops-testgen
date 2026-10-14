"""A table group's schema reaches the flavors that read it when a connection opens."""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from testgen.common.database import database_service
from testgen.common.database.flavor.flavor_service import resolve_connection_params
from testgen.common.database.flavor.salesforce_data360_flavor_service import SalesforceData360FlavorService
from testgen.common.database.flavor.snowflake_flavor_service import SnowflakeFlavorService

pytestmark = pytest.mark.unit

FLAVOR_MODULE = "testgen.common.database.flavor.flavor_service"

SALESFORCE_PARAMS = {
    "sql_flavor": "salesforce_data360",
    "project_host": "https://myorg.my.salesforce.com",
    "project_user": "consumer_key",
    "project_pw_encrypted": "consumer_secret",
}
SNOWFLAKE_PARAMS = {
    "sql_flavor": "snowflake",
    "project_host": "acme.us-east-1",
    "project_port": "443",
    "project_user": "tg_user",
    "project_pw_encrypted": "secret",
    "project_db": "ANALYTICS",
}


def _engine_call(flavor_service, connection_params, table_group_schema):
    with patch(f"{FLAVOR_MODULE}.sqlalchemy_create_engine") as create:
        flavor_service.create_engine(connection_params, table_group_schema)
    return create.call_args


def test_a_stray_schema_key_on_connection_params_is_ignored():
    params = resolve_connection_params({**SNOWFLAKE_PARAMS, "table_group_schema": "STRAY"})
    assert params.dbschema is None


def test_a_salesforce_engine_opened_for_a_table_group_uses_its_data_space():
    call = _engine_call(SalesforceData360FlavorService(), SALESFORCE_PARAMS, "marketing")
    assert call.kwargs["connect_args"]["dataspace"] == "marketing"


def test_a_salesforce_engine_opened_for_no_table_group_uses_the_default_data_space():
    call = _engine_call(SalesforceData360FlavorService(), SALESFORCE_PARAMS, None)
    assert "dataspace" not in call.kwargs["connect_args"]


def test_salesforce_discovery_lists_the_objects_of_the_table_groups_data_space():
    params = resolve_connection_params(SALESFORCE_PARAMS)
    connector = MagicMock()
    connector.return_value.list_tables.return_value = []

    with patch("salesforcecdpconnector.connection.SalesforceCDPConnection", connector):
        SalesforceData360FlavorService().get_schema_columns(params, "marketing")

    assert connector.call_args.kwargs["dataspace"] == "marketing"


@pytest.mark.parametrize(("table_group_schema", "path"), [("SALES", "/ANALYTICS/SALES?"), (None, "/ANALYTICS/?")])
def test_a_snowflake_session_opens_in_the_table_groups_schema(table_group_schema, path):
    call = _engine_call(SnowflakeFlavorService(), SNOWFLAKE_PARAMS, table_group_schema)
    assert path in str(call.args[0])


@pytest.mark.parametrize(
    ("connect_by_url", "table_group_schema", "use_schema"),
    [
        pytest.param(True, "Sales", 'USE SCHEMA "Sales";', id="url_with_schema"),
        pytest.param(True, 'odd"name', 'USE SCHEMA "odd""name";', id="url_quote_in_schema"),
        pytest.param(True, None, None, id="url_without_schema"),
        pytest.param(False, "SALES", None, id="fields_carry_schema_in_url"),
    ],
)
def test_a_snowflake_url_session_switches_to_the_table_groups_schema(connect_by_url, table_group_schema, use_schema):
    connection_params = {
        **SNOWFLAKE_PARAMS,
        "connect_by_url": connect_by_url,
        "url": "acme.snowflakecomputing.com:443/ANALYTICS/?account=acme",
    }
    params = resolve_connection_params(connection_params, table_group_schema)

    queries = [query for query, _ in SnowflakeFlavorService().get_pre_connection_queries(params)]

    assert [query for query in queries if query.startswith("USE SCHEMA")] == ([use_schema] if use_schema else [])


def test_a_job_opens_its_target_engine_with_the_table_group_schema():
    flavor_service = MagicMock()
    flavor_service.get_pre_connection_queries.return_value = []
    table_group = MagicMock(table_group_schema="marketing", file_declarations=None)

    with ExitStack() as stack:
        stack.enter_context(patch.object(database_service, "target_db_params", None))
        stack.enter_context(patch.object(database_service, "engine_cache", database_service.EngineCache()))
        stack.enter_context(patch.object(database_service, "get_flavor_service", return_value=flavor_service))
        stack.enter_context(patch.object(database_service, "initialize_connection"))
        database_service.set_target_db_params(SALESFORCE_PARAMS, table_group)
        database_service._init_target_db_connection()

    flavor_service.create_engine.assert_called_once_with(SALESFORCE_PARAMS, "marketing")


def test_an_ad_hoc_target_session_opens_its_engine_with_the_table_group_schema():
    from testgen.ui.services import database_service as ui_database_service

    connection = MagicMock(sql_flavor="salesforce_data360")
    connection.to_dict.return_value = SALESFORCE_PARAMS
    flavor_service = MagicMock()
    flavor_service.get_pre_connection_queries.return_value = []
    table_group = MagicMock(table_group_schema="marketing", file_declarations=None)

    with (
        patch.object(ui_database_service, "get_flavor_service", return_value=flavor_service),
        patch.object(ui_database_service, "initialize_connection"),
        ui_database_service.target_db_session(connection, table_group),
    ):
        pass

    flavor_service.create_engine.assert_called_once_with(SALESFORCE_PARAMS, "marketing")
