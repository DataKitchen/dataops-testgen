from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event, text

from testgen.common.database import statement_cancel
from testgen.common.database.flavor.flavor_service import FlavorService
from testgen.common.database.statement_cancel import (
    RunningStatement,
    StatementsCanceled,
    cancel_target_statements,
    track_statements,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def fresh_registry():
    statement_cancel.reset()
    yield
    statement_cancel.reset()


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    yield engine
    engine.dispose()


def test_a_running_statement_is_canceled_through_its_connection_type(engine):
    flavor_service = MagicMock()
    track_statements(engine, flavor_service)
    seen: list[RunningStatement] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _cancel_mid_statement(*_args):
        # Registered after the tracker, so it runs while the statement is tracked.
        cancel_target_statements()

    flavor_service.cancel_statement.side_effect = seen.append

    with engine.connect() as connection, pytest.raises(StatementsCanceled):
        connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT 2"))

    [statement] = seen
    assert statement.engine is engine
    assert statement.cursor is not None
    assert statement.dbapi_connection is not None


def test_a_finished_statement_is_no_longer_canceled(engine):
    flavor_service = MagicMock()
    track_statements(engine, flavor_service)

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    assert cancel_target_statements() == 0
    flavor_service.cancel_statement.assert_not_called()


def test_a_failed_statement_is_no_longer_canceled(engine):
    flavor_service = MagicMock()
    track_statements(engine, flavor_service)

    with engine.connect() as connection, pytest.raises(Exception, match="no such table"):
        connection.execute(text("SELECT * FROM missing"))

    assert cancel_target_statements() == 0


def test_no_statement_starts_once_statements_were_canceled(engine):
    track_statements(engine, MagicMock())
    cancel_target_statements()

    with engine.connect() as connection, pytest.raises(StatementsCanceled):
        connection.execute(text("SELECT 1"))


def test_a_failed_cancel_does_not_stop_the_others(caplog):
    first, second = MagicMock(), MagicMock()
    first.cancel_statement.side_effect = RuntimeError("driver refused")
    second.cancel_statement.return_value = True
    statement_cancel._running.update({
        1: (MagicMock(), first),
        2: (MagicMock(), second),
    })

    assert cancel_target_statements() == 1
    second.cancel_statement.assert_called_once()
    assert "Could not cancel a running query" in caplog.text


def test_a_connection_type_without_a_cancel_lets_its_statement_run():
    assert FlavorService().cancel_statement(MagicMock()) is False
