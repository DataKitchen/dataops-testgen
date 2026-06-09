from unittest.mock import MagicMock, patch

import pytest

from testgen.common.data_catalog_service import (
    TableSampleResult,
    build_create_table_script,
    fetch_table_sample,
    render_create_table_script,
)
from testgen.common.models.data_column import CreateScriptColumn

pytestmark = pytest.mark.unit

MODULE = "testgen.common.data_catalog_service"


def _flavor_service(table_ref='"demo"."orders"', limit_clauses=("", "LIMIT 100")):
    fs = MagicMock()
    fs.quote_character = '"'
    fs.get_table_ref.return_value = table_ref
    fs.row_limit_clauses.return_value = limit_clauses
    return fs


def _column(name, db_type="varchar(50)", suggestion="VARCHAR(20)"):
    return CreateScriptColumn(column_name=name, db_data_type=db_type, datatype_suggestion=suggestion)


# ---------------------------------------------------------------------------
# render_create_table_script
# ---------------------------------------------------------------------------

def test_render_uses_suggested_type_and_quotes_identifiers():
    fs = _flavor_service()
    columns = [_column("id", "int", "INTEGER"), _column("name", "text", "VARCHAR(20)")]

    script = render_create_table_script("demo", "orders", columns, fs)

    assert script.startswith('CREATE TABLE "demo"."orders" (')
    assert '"id"' in script
    assert '"name"' in script
    assert "INTEGER" in script
    assert "VARCHAR(20)" in script


def test_render_omits_was_annotations_by_default():
    fs = _flavor_service()
    columns = [_column("name", db_type="text", suggestion="VARCHAR(20)")]

    script = render_create_table_script("demo", "orders", columns, fs)

    assert "-- WAS" not in script


def test_render_includes_was_annotations_when_enabled():
    fs = _flavor_service()
    columns = [_column("name", db_type="text", suggestion="VARCHAR(20)")]

    script = render_create_table_script("demo", "orders", columns, fs, annotate_changes=True)

    assert "-- WAS text" in script


def test_render_no_was_annotation_when_type_unchanged():
    fs = _flavor_service()
    columns = [_column("name", db_type="VARCHAR(20)", suggestion="VARCHAR(20)")]

    script = render_create_table_script("demo", "orders", columns, fs, annotate_changes=True)

    assert "-- WAS" not in script


def test_render_falls_back_to_db_type_when_no_suggestion():
    fs = _flavor_service()
    columns = [_column("name", db_type="text", suggestion=None)]

    script = render_create_table_script("demo", "orders", columns, fs)

    assert "text" in script


def test_render_only_last_column_has_no_trailing_comma():
    fs = _flavor_service()
    columns = [_column("a", "int", "INTEGER"), _column("b", "int", "INTEGER")]

    script = render_create_table_script("demo", "orders", columns, fs)

    body_lines = [line for line in script.splitlines() if '"a"' in line or '"b"' in line]
    assert body_lines[0].rstrip().endswith(",")
    assert not body_lines[1].rstrip().endswith(",")


# ---------------------------------------------------------------------------
# build_create_table_script
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.DataColumnChars")
def test_build_returns_none_when_no_columns(mock_columns):
    mock_columns.list_for_create_script.return_value = (None, [])

    assert build_create_table_script("tg-id", "orders") is None


@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.DataColumnChars")
def test_build_renders_script_for_existing_table(mock_columns, mock_conn, mock_flavor):
    mock_columns.list_for_create_script.return_value = ("demo", [_column("id", "int", "INTEGER")])
    mock_conn.get_by_table_group.return_value = MagicMock(sql_flavor="postgresql")
    mock_flavor.return_value = _flavor_service()

    script = build_create_table_script("tg-id", "orders")

    assert script is not None
    assert "CREATE TABLE" in script
    assert "INTEGER" in script


# ---------------------------------------------------------------------------
# fetch_table_sample
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.fetch_from_target_db")
@patch(f"{MODULE}.get_flavor_service")
def test_fetch_sample_ok(mock_flavor, mock_fetch):
    mock_flavor.return_value = _flavor_service()
    mock_fetch.return_value = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    connection = MagicMock(sql_flavor="postgresql")

    result = fetch_table_sample(connection, "tg-id", "demo", "orders", limit=100, mask_pii=False)

    assert result.status == "OK"
    assert len(result.df) == 2
    assert result.pii_redacted is False


@patch(f"{MODULE}.fetch_from_target_db")
@patch(f"{MODULE}.get_flavor_service")
def test_fetch_sample_builds_distinct_limited_query(mock_flavor, mock_fetch):
    mock_flavor.return_value = _flavor_service(limit_clauses=("", "LIMIT 50"))
    mock_fetch.return_value = [{"id": 1}]
    connection = MagicMock(sql_flavor="postgresql")

    fetch_table_sample(connection, "tg-id", "demo", "orders", limit=50, mask_pii=False)

    query = mock_fetch.call_args.args[1]
    assert "SELECT DISTINCT" in query
    assert "LIMIT 50" in query
    assert '"demo"."orders"' in query


@patch(f"{MODULE}.fetch_from_target_db")
@patch(f"{MODULE}.get_flavor_service")
def test_fetch_sample_empty_returns_nd(mock_flavor, mock_fetch):
    mock_flavor.return_value = _flavor_service()
    mock_fetch.return_value = []
    connection = MagicMock(sql_flavor="postgresql")

    result = fetch_table_sample(connection, "tg-id", "demo", "orders", limit=100, mask_pii=False)

    assert result.status == "ND"


@patch(f"{MODULE}.fetch_from_target_db", side_effect=Exception("connection refused"))
@patch(f"{MODULE}.get_flavor_service")
def test_fetch_sample_error_returns_err(mock_flavor, _mock_fetch):
    mock_flavor.return_value = _flavor_service()
    connection = MagicMock(sql_flavor="postgresql")

    result = fetch_table_sample(connection, "tg-id", "demo", "orders", limit=100, mask_pii=False)

    assert result.status == "ERR"


@patch(f"{MODULE}.get_pii_columns", return_value={"name"})
@patch(f"{MODULE}.fetch_from_target_db")
@patch(f"{MODULE}.get_flavor_service")
def test_fetch_sample_masks_pii_columns(mock_flavor, mock_fetch, _mock_pii):
    mock_flavor.return_value = _flavor_service()
    mock_fetch.return_value = [{"id": 1, "name": "secret"}]
    connection = MagicMock(sql_flavor="postgresql")

    result = fetch_table_sample(connection, "tg-id", "demo", "orders", limit=100, mask_pii=True)

    assert result.status == "OK"
    assert result.pii_redacted is True
    assert "secret" not in result.df["name"].tolist()


def test_table_sample_result_defaults():
    result = TableSampleResult("ND")
    assert result.df is None
    assert result.pii_redacted is False
