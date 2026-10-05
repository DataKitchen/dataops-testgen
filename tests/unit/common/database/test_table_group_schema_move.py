"""Guards on moving a table group's schema, which run before anything is written."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.database.table_group_service import (
    SchemaMove,
    SchemaMoveRefused,
    _has_job_in_flight,
    apply_schema_move,
    move_table_group_schema,
)
from testgen.common.flavors import SqlFlavorCode

pytestmark = pytest.mark.unit

MODULE = "testgen.common.database.table_group_service"


def _table_group(schema: str = "public") -> MagicMock:
    return MagicMock(id=uuid4(), connection_id=uuid4(), table_group_schema=schema)


def _connection(flavor_code: str) -> MagicMock:
    return MagicMock(sql_flavor_code=flavor_code)


def test_an_unchanged_schema_moves_nothing():
    table_group = _table_group("public")

    move = move_table_group_schema(table_group, "public", connection=_connection(SqlFlavorCode.POSTGRESQL))

    assert move.definitions_repointed == 0
    assert move.missing_tables == []
    assert table_group.table_group_schema == "public"


@pytest.mark.parametrize(
    "flavor_code",
    [SqlFlavorCode.FILES, SqlFlavorCode.S3, SqlFlavorCode.AZURE_BLOB],
)
def test_a_connection_whose_tables_are_files_has_nothing_to_move_to(flavor_code):
    """Those tables are declared as paths, and the stored schema is fixed for every table group on
    the connection, so a move would write a value nothing reads."""
    table_group = _table_group("main")

    with pytest.raises(SchemaMoveRefused) as refusal:
        move_table_group_schema(table_group, "onboard_2026_09_16", connection=_connection(flavor_code))

    assert refusal.value.reason == "schema_unsupported"
    assert table_group.table_group_schema == "main"


def test_the_connection_is_checked_before_the_name():
    """A connection with no schema to move to is refused whatever the name looks like, so the
    caller is told the operation does not apply rather than to fix the name."""
    with pytest.raises(SchemaMoveRefused) as refusal:
        move_table_group_schema(_table_group("main"), "not a valid name", connection=_connection(SqlFlavorCode.FILES))

    assert refusal.value.reason == "schema_unsupported"


@patch(f"{MODULE}._has_job_in_flight", return_value=False)
def test_a_database_connection_passes_the_flavor_guard(_mock_job):
    """The guard rejects only schemaless connections; a database one goes on to the name check."""
    with pytest.raises(SchemaMoveRefused) as refusal:
        move_table_group_schema(
            _table_group("public"), "not a valid name", connection=_connection(SqlFlavorCode.POSTGRESQL)
        )

    assert refusal.value.reason == "invalid_schema_name"


@patch(f"{MODULE}._has_job_in_flight", return_value=True)
def test_a_job_in_flight_is_refused_before_the_target_is_probed(_mock_job):
    """Probing costs a round trip to the target database, and the answer would not matter."""
    with patch(f"{MODULE}.preview_table_group") as mock_preview:
        with pytest.raises(SchemaMoveRefused) as refusal:
            move_table_group_schema(
                _table_group("public"), "onboard_2026_09_16", connection=_connection(SqlFlavorCode.POSTGRESQL)
            )

    assert refusal.value.reason == "job_in_flight"
    mock_preview.assert_not_called()


# --- the catalog write is handed back, not run ---


def _preview(tables: dict) -> tuple:
    return ({"tables": tables, "success": True, "message": None}, [MagicMock()], MagicMock())


@patch(f"{MODULE}.make_save_data_chars")
@patch(f"{MODULE}._tables_in_use", return_value=set())
@patch(f"{MODULE}._repoint_definitions", return_value=3)
@patch(f"{MODULE}._has_job_in_flight", return_value=False)
def test_the_move_does_not_write_the_catalog_itself(_job, _repoint, _in_use, mock_make, ):
    """The catalog writes on its own connection and commits there, so a caller whose transaction
    then fails would be left with a catalog naming a schema nothing else points at."""
    callback = MagicMock()
    mock_make.return_value = callback
    table_group = _table_group("public")

    with patch(f"{MODULE}.preview_table_group", return_value=_preview({"orders": {}})):
        move = move_table_group_schema(
            table_group, "onboard_2026_09_16", connection=_connection(SqlFlavorCode.POSTGRESQL)
        )

    callback.assert_not_called()
    assert move.refresh_catalog is callback
    assert table_group.table_group_schema == "onboard_2026_09_16"


@patch(f"{MODULE}.get_current_session")
def test_applying_a_move_commits_before_writing_the_catalog(mock_session):
    """Ordering is the whole point: the catalog must describe a move that is already durable."""
    calls = []
    session = MagicMock()
    session.commit.side_effect = lambda: calls.append("commit")
    mock_session.return_value = session
    move = SchemaMove(
        previous_schema="public",
        schema="onboard_2026_09_16",
        missing_tables=[],
        definitions_repointed=0,
        refresh_catalog=lambda _id: calls.append("catalog"),
    )

    apply_schema_move(move, uuid4())

    assert calls == ["commit", "catalog"]


@patch(f"{MODULE}.get_current_session")
def test_a_failing_catalog_write_does_not_undo_the_move(mock_session):
    """The catalog is derived state the next refresh rebuilds; the move is not."""
    move = SchemaMove(
        previous_schema="public",
        schema="onboard_2026_09_16",
        missing_tables=[],
        definitions_repointed=0,
        refresh_catalog=MagicMock(side_effect=RuntimeError("target unreachable")),
    )

    apply_schema_move(move, uuid4())

    mock_session.return_value.commit.assert_called_once()


# --- which jobs block a move ---


@patch(f"{MODULE}.get_current_session")
def test_every_job_kwarg_naming_the_table_group_blocks_a_move(mock_session):
    """A job already running reads the schema while it changes.

    Monitor generation names its suite under ``monitor_suite_id`` rather than ``test_suite_id``,
    and profiling enqueues it as a follow-up, so it is the job most likely to be in flight.
    """
    session = MagicMock()
    mock_session.return_value = session
    session.scalars.return_value.all.return_value = []
    session.scalars.return_value.first.return_value = None

    _has_job_in_flight(_table_group())

    # The JSONB keys are bound parameters, so they are read off the compiled statement rather
    # than matched in its text.
    compiled = session.scalars.call_args_list[-1].args[0].compile(dialect=postgresql.dialect())
    probed = {value for value in compiled.params.values() if isinstance(value, str)}
    for key in ("table_group_id", "test_suite_id", "monitor_suite_id"):
        assert key in probed, f"a job naming the table group under {key} would not block a move"


# --- telling an unreadable schema from an empty one ---


@patch(f"{MODULE}._has_job_in_flight", return_value=False)
def test_a_schema_that_cannot_be_read_says_so(_job):
    """A probe that raised and a schema that held nothing both come back as a failed preview, and
    reporting the wrong one sends the caller to their table-group filters over a dead connection."""
    failed = ({"tables": {}, "success": False, "message": "could not connect to server"}, None, None)

    with patch(f"{MODULE}.preview_table_group", return_value=failed):
        with pytest.raises(SchemaMoveRefused) as refusal:
            move_table_group_schema(
                _table_group("public"), "onboard_2026_09_16", connection=_connection(SqlFlavorCode.POSTGRESQL)
            )

    assert refusal.value.reason == "schema_unreadable"
    assert "could not connect to server" in refusal.value.message


@patch(f"{MODULE}._has_job_in_flight", return_value=False)
def test_a_schema_that_holds_nothing_says_that_instead(_job):
    empty = ({"tables": {}, "success": False, "message": "No tables found"}, [], MagicMock())

    with patch(f"{MODULE}.preview_table_group", return_value=empty):
        with pytest.raises(SchemaMoveRefused) as refusal:
            move_table_group_schema(
                _table_group("public"), "onboard_2026_09_16", connection=_connection(SqlFlavorCode.POSTGRESQL)
            )

    assert refusal.value.reason == "schema_empty"
