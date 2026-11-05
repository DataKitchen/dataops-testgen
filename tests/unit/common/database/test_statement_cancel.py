import threading
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event, text

from testgen.common.database import database_service
from testgen.common.database.flavor.flavor_service import FlavorService
from testgen.common.database.statement_cancel import (
    RunningStatement,
    StatementsCanceled,
    cancel_each,
    cancel_statements,
    track_statements,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    yield engine
    engine.dispose()


def test_a_running_statement_is_canceled_through_its_connection_type(engine):
    flavor_service = MagicMock()
    flavor_service.cancel_statements.return_value = 1
    track_statements(engine, flavor_service)

    @event.listens_for(engine, "before_cursor_execute")
    def _cancel_mid_statement(*_args):
        # Registered after the tracker, so it runs while the statement is tracked.
        cancel_statements(engine)

    with engine.connect() as connection, pytest.raises(StatementsCanceled):
        connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT 2"))

    [[statement]] = flavor_service.cancel_statements.call_args.args
    assert statement.engine is engine
    assert statement.cursor is not None
    assert statement.dbapi_connection is not None


def test_a_finished_statement_is_no_longer_canceled(engine):
    flavor_service = MagicMock()
    track_statements(engine, flavor_service)

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    assert cancel_statements(engine) == 0
    flavor_service.cancel_statements.assert_not_called()


def test_a_failed_statement_is_no_longer_canceled(engine):
    flavor_service = MagicMock()
    track_statements(engine, flavor_service)

    with engine.connect() as connection, pytest.raises(Exception, match="no such table"):
        connection.execute(text("SELECT * FROM missing"))

    assert cancel_statements(engine) == 0


def test_no_statement_starts_on_any_thread_once_the_engine_canceled(engine):
    track_statements(engine, MagicMock())
    cancel_statements(engine)
    refused = []

    def run():
        with engine.connect() as connection:
            try:
                connection.execute(text("SELECT 1"))
            except StatementsCanceled:
                refused.append(True)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    assert refused == [True]


def test_a_cancel_leaves_other_engines_running(engine):
    other = create_engine("sqlite://")
    track_statements(engine, MagicMock())
    track_statements(other, MagicMock())

    cancel_statements(engine)

    with other.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar() == 1
    other.dispose()


def test_an_untracked_engine_has_nothing_to_cancel(engine):
    assert cancel_statements(engine) == 0
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar() == 1


def test_a_failed_cancel_does_not_stop_the_others(caplog):
    def cancel(item):
        if item == "first":
            raise RuntimeError("driver refused")
        return True

    assert cancel_each(["first", "second"], cancel) == 1
    assert "Could not cancel a running query" in caplog.text


def test_a_connection_type_without_a_cancel_lets_its_statements_run():
    assert FlavorService().cancel_statements([MagicMock(spec=RunningStatement)]) == 0


def test_the_job_target_engine_is_tracked_when_it_is_created():
    flavor_service = MagicMock()
    flavor_service.get_pre_connection_queries.return_value = []
    params = {"sql_flavor": "postgresql", "sql_flavor_code": "postgresql"}

    with (
        patch.object(database_service, "target_db_params", None),
        patch.object(database_service, "engine_cache", database_service.EngineCache()),
        patch.object(database_service, "get_flavor_service", return_value=flavor_service),
        patch.object(database_service, "resolve_connection_params"),
        patch.object(database_service, "initialize_connection"),
        patch.object(database_service, "track_statements") as track,
    ):
        database_service.set_target_db_params(params, None)
        database_service._init_target_db_connection()
        database_service._init_target_db_connection()

    track.assert_called_once_with(flavor_service.create_engine.return_value, flavor_service)


def test_canceling_the_target_reaches_the_job_s_target_engine(engine):
    flavor_service = MagicMock()
    flavor_service.cancel_statements.return_value = 1
    track_statements(engine, flavor_service)

    with patch.object(database_service, "engine_cache", database_service.EngineCache(target_db=engine)):
        database_service.cancel_target_statements()

    with engine.connect() as connection, pytest.raises(StatementsCanceled):
        connection.execute(text("SELECT 1"))


def test_canceling_with_no_target_engine_does_nothing():
    with patch.object(database_service, "engine_cache", database_service.EngineCache()):
        assert database_service.cancel_target_statements() == 0
