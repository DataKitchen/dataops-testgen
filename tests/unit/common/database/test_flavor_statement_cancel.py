from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from google.cloud.bigquery import QueryJobConfig
from sqlalchemy.exc import ProgrammingError

from testgen.common.database.flavor.bigquery_flavor_service import (
    RUN_LABEL,
    BigqueryFlavorService,
    _label_run_queries,
)
from testgen.common.database.flavor.databricks_flavor_service import DatabricksFlavorService
from testgen.common.database.flavor.duckdb_flavor_service import DuckdbFlavorService
from testgen.common.database.flavor.mssql_flavor_service import MssqlFlavorService
from testgen.common.database.flavor.oracle_flavor_service import OracleFlavorService
from testgen.common.database.flavor.postgresql_flavor_service import PostgresqlFlavorService
from testgen.common.database.flavor.redshift_flavor_service import RedshiftFlavorService
from testgen.common.database.flavor.salesforce_data360_flavor_service import SalesforceData360FlavorService
from testgen.common.database.flavor.sap_hana_flavor_service import SapHanaFlavorService
from testgen.common.database.flavor.snowflake_flavor_service import SnowflakeFlavorService
from testgen.common.database.statement_cancel import RunningStatement
from testgen.common.enums import JobSource
from testgen.common.job_context import JobContext, job_context

pytestmark = pytest.mark.unit


def _statement() -> RunningStatement:
    return RunningStatement(engine=MagicMock(), dbapi_connection=MagicMock(), cursor=MagicMock())


@pytest.mark.parametrize(
    "service", [PostgresqlFlavorService(), RedshiftFlavorService(), OracleFlavorService(), SapHanaFlavorService()],
)
def test_connection_types_that_cancel_through_the_busy_connection(service):
    statement = _statement()

    assert service.cancel_statement(statement) is True
    statement.dbapi_connection.cancel.assert_called_once_with()


def test_sql_server_cancels_through_the_cursor():
    statement = _statement()

    assert MssqlFlavorService().cancel_statement(statement) is True
    statement.cursor.cancel.assert_called_once_with()


def test_duckdb_interrupts_the_connection():
    statement = _statement()

    assert DuckdbFlavorService().cancel_statement(statement) is True
    statement.dbapi_connection.interrupt.assert_called_once_with()


def test_snowflake_cancels_the_session_s_queries_from_a_connection_of_its_own():
    statement = _statement()
    statement.dbapi_connection.session_id = 4242
    other = statement.engine.raw_connection.return_value
    cursor = other.cursor.return_value.__enter__.return_value

    assert SnowflakeFlavorService().cancel_statement(statement) is True
    cursor.execute.assert_called_once_with("SELECT SYSTEM$CANCEL_ALL_QUERIES(%s)", (4242,))
    other.close.assert_called_once()
    statement.dbapi_connection.cursor.assert_not_called()


def test_databricks_cancels_the_command_from_a_connection_of_its_own():
    statement = _statement()
    statement.cursor.active_command_id = "command-1"
    other = statement.engine.raw_connection.return_value

    assert DatabricksFlavorService().cancel_statement(statement) is True
    other.dbapi_connection.session.backend.cancel_command.assert_called_once_with("command-1")
    other.close.assert_called_once()


def test_databricks_has_nothing_to_cancel_before_the_command_starts():
    statement = _statement()
    statement.cursor.active_command_id = None

    assert DatabricksFlavorService().cancel_statement(statement) is False
    statement.engine.raw_connection.assert_not_called()


def test_salesforce_data360_lets_its_statements_finish():
    assert SalesforceData360FlavorService().cancel_statement(_statement()) is False


# ---- BigQuery -----------------------------------------------------------------------------


@pytest.fixture
def run_id():
    run_id = uuid4()
    token = job_context.set(JobContext(job_id=run_id, source=JobSource.scheduler))
    yield run_id
    job_context.reset(token)


def test_bigquery_labels_a_run_s_queries_with_the_run(run_id):
    client = SimpleNamespace(default_query_job_config=QueryJobConfig(labels={"team": "data"}))

    _label_run_queries(SimpleNamespace(_client=client), None)

    assert client.default_query_job_config.labels == {"team": "data", RUN_LABEL: str(run_id)}


def test_bigquery_labels_nothing_outside_a_run():
    client = SimpleNamespace(default_query_job_config=None)

    _label_run_queries(SimpleNamespace(_client=client), None)

    assert client.default_query_job_config is None


def test_bigquery_cancels_only_the_run_s_own_jobs(run_id):
    statement = _statement()
    client = statement.dbapi_connection._client
    own = SimpleNamespace(job_id="own", location="US", labels={RUN_LABEL: str(run_id)})
    other = SimpleNamespace(job_id="other", location="US", labels={RUN_LABEL: str(uuid4())})
    unlabeled = SimpleNamespace(job_id="unlabeled", location="US", labels=None)
    client.list_jobs.return_value = [own, other, unlabeled]

    assert BigqueryFlavorService().cancel_statement(statement) is True
    client.list_jobs.assert_called_once_with(state_filter="running")
    client.cancel_job.assert_called_once_with("own", location="US")


def test_bigquery_cancels_nothing_outside_a_run():
    statement = _statement()

    assert BigqueryFlavorService().cancel_statement(statement) is False
    statement.dbapi_connection._client.list_jobs.assert_not_called()


# ---- PostgreSQL ---------------------------------------------------------------------------


def test_postgresql_checks_for_a_vanished_client_and_keeps_the_setting():
    connection = MagicMock()

    PostgresqlFlavorService().init(connection, MagicMock(), [])

    statement = str(connection.execute.call_args.args[0])
    assert statement == "SET client_connection_check_interval = '5s'"
    connection.begin_nested.assert_called_once()
    connection.commit.assert_called_once()


def test_postgresql_that_refuses_the_setting_still_connects():
    connection = MagicMock()
    connection.execute.side_effect = ProgrammingError("SET", {}, Exception("unrecognized configuration parameter"))

    PostgresqlFlavorService().init(connection, MagicMock(), [])

    connection.commit.assert_called_once()
