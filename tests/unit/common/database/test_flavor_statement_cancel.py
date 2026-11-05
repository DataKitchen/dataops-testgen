from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from google.cloud.bigquery import QueryJobConfig
from sqlalchemy.exc import ProgrammingError

from testgen.common.database.database_service import run_keyed_worker_pool
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


def _statements(count: int) -> list[RunningStatement]:
    engine = MagicMock()
    return [RunningStatement(engine=engine, dbapi_connection=MagicMock(), cursor=MagicMock()) for _ in range(count)]


def test_snowflake_cancels_every_session_through_one_connection_of_its_own():
    statements = _statements(3)
    for session_id, statement in enumerate(statements):
        statement.dbapi_connection.session_id = session_id
    engine = statements[0].engine
    cursor = engine.raw_connection.return_value.cursor.return_value.__enter__.return_value

    assert SnowflakeFlavorService().cancel_statements(statements) == 3
    engine.raw_connection.assert_called_once()
    assert [c.args for c in cursor.execute.call_args_list] == [
        ("SELECT SYSTEM$CANCEL_ALL_QUERIES(%s)", (session_id,)) for session_id in range(3)
    ]
    engine.raw_connection.return_value.close.assert_called_once()


def test_snowflake_keeps_canceling_after_one_session_fails():
    statements = _statements(2)
    cursor = statements[0].engine.raw_connection.return_value.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = [RuntimeError("session gone"), None]

    assert SnowflakeFlavorService().cancel_statements(statements) == 1


def test_databricks_cancels_every_command_through_one_connection_of_its_own():
    statements = _statements(3)
    statements[0].cursor.active_command_id = "command-1"
    statements[1].cursor.active_command_id = None
    statements[2].cursor.active_command_id = "command-3"
    engine = statements[0].engine
    backend = engine.raw_connection.return_value.dbapi_connection.session.backend

    assert DatabricksFlavorService().cancel_statements(statements) == 2
    engine.raw_connection.assert_called_once()
    assert [c.args for c in backend.cancel_command.call_args_list] == [("command-1",), ("command-3",)]
    engine.raw_connection.return_value.close.assert_called_once()


def test_databricks_opens_no_connection_before_any_command_starts():
    statements = _statements(2)
    for statement in statements:
        statement.cursor.active_command_id = None

    assert DatabricksFlavorService().cancel_statements(statements) == 0
    statements[0].engine.raw_connection.assert_not_called()


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


def test_bigquery_labels_a_connection_a_pool_worker_opens(run_id):
    """Most connections are opened on a worker of the job's query pool, not on the job's thread."""
    client = SimpleNamespace(default_query_job_config=None)

    list(run_keyed_worker_pool([("connect", None)], lambda _arg: _label_run_queries(SimpleNamespace(_client=client), None)))

    assert client.default_query_job_config.labels == {RUN_LABEL: str(run_id)}


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
