"""Tests for testgen.common.custom_test_validation."""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest
import yaml

import testgen
from testgen.common.custom_test_validation import (
    CustomQueryResult,
    InvalidMetricQuery,
    render_metric_validation_query,
    validate_custom_query,
    validate_metric_query,
)
from testgen.common.database.flavor.flavor_service import FlavorService


def _flavor_service(row_limiting: str = "limit") -> FlavorService:
    svc = FlavorService()
    svc.row_limiting_clause = row_limiting  # type: ignore[assignment]
    return svc


def _connection(flavor: str = "postgresql") -> MagicMock:
    conn = MagicMock()
    conn.sql_flavor = flavor
    return conn


# -- validate_custom_query ----------------------------------------------------


@patch("testgen.common.custom_test_validation.fetch_from_target_db")
@patch("testgen.common.custom_test_validation.get_flavor_service")
def test_validate_custom_query_count_only(mock_get_flavor, mock_fetch):
    mock_get_flavor.return_value = _flavor_service("limit")
    mock_fetch.return_value = [{"row_count": 0}]

    result = validate_custom_query(
        _connection(), "demo", "SELECT * FROM orders WHERE total < 0",
    )

    assert isinstance(result, CustomQueryResult)
    assert result.row_count == 0
    assert result.preview_rows == []
    # Only one fetch call: the count query
    assert mock_fetch.call_count == 1
    # Verify the count query is wrapped with ERR_TABLE
    count_sql = mock_fetch.call_args_list[0].args[1]
    assert "SELECT COUNT(*)" in count_sql
    assert "ERR_TABLE" in count_sql


@patch("testgen.common.custom_test_validation.fetch_from_target_db")
@patch("testgen.common.custom_test_validation.get_flavor_service")
def test_validate_custom_query_with_preview(mock_get_flavor, mock_fetch):
    mock_get_flavor.return_value = _flavor_service("limit")
    preview_row = MagicMock()
    preview_row.keys.return_value = ["order_id", "amount"]
    mock_fetch.side_effect = [
        [{"row_count": 3}],  # count query result
        [preview_row],  # preview query result
    ]

    result = validate_custom_query(
        _connection(), "demo", "SELECT * FROM orders WHERE total < 0", preview_limit=1,
    )

    assert result.row_count == 3
    assert result.preview_rows == [preview_row]
    assert mock_fetch.call_count == 2
    preview_sql = mock_fetch.call_args_list[1].args[1]
    assert "SELECT" in preview_sql
    assert "ERR_TABLE" in preview_sql
    assert "LIMIT 1" in preview_sql


@patch("testgen.common.custom_test_validation.fetch_from_target_db")
@patch("testgen.common.custom_test_validation.get_flavor_service")
def test_validate_custom_query_preview_skipped_when_no_rows(mock_get_flavor, mock_fetch):
    mock_get_flavor.return_value = _flavor_service("limit")
    mock_fetch.return_value = [{"row_count": 0}]

    result = validate_custom_query(
        _connection(), "demo", "SELECT 1 WHERE 1=0", preview_limit=5,
    )

    assert result.row_count == 0
    assert result.preview_rows == []
    # Preview query should NOT run when count is 0
    assert mock_fetch.call_count == 1


@patch("testgen.common.custom_test_validation.fetch_from_target_db")
@patch("testgen.common.custom_test_validation.get_flavor_service")
def test_validate_custom_query_substitutes_data_schema(mock_get_flavor, mock_fetch):
    mock_get_flavor.return_value = _flavor_service("limit")
    mock_fetch.return_value = [{"row_count": 0}]

    validate_custom_query(
        _connection(),
        "production_schema",
        "SELECT * FROM {DATA_SCHEMA}.orders",
    )

    count_sql = mock_fetch.call_args_list[0].args[1]
    # {DATA_SCHEMA} was substituted with the actual schema name
    assert "production_schema.orders" in count_sql
    assert "{DATA_SCHEMA}" not in count_sql


@patch("testgen.common.custom_test_validation.fetch_from_target_db")
@patch("testgen.common.custom_test_validation.get_flavor_service")
def test_validate_custom_query_strips_trailing_semicolon(mock_get_flavor, mock_fetch):
    """Trailing semicolons break the subquery wrap — must be stripped."""
    mock_get_flavor.return_value = _flavor_service("limit")
    mock_fetch.return_value = [{"row_count": 0}]

    validate_custom_query(
        _connection(), "demo", "SELECT 1;  ",
    )

    count_sql = mock_fetch.call_args_list[0].args[1]
    # The subquery should not contain a trailing semicolon
    assert "SELECT 1)" in count_sql or "SELECT 1 )" in count_sql
    # Specifically, the inner SELECT 1 should not be followed by ; inside the wrap
    assert "SELECT 1;" not in count_sql


@patch("testgen.common.custom_test_validation.fetch_from_target_db")
@patch("testgen.common.custom_test_validation.get_flavor_service")
def test_validate_custom_query_uses_flavor_specific_limit(mock_get_flavor, mock_fetch):
    """Oracle uses FETCH FIRST; MSSQL uses TOP — preview SQL must respect the flavor."""
    mock_get_flavor.return_value = _flavor_service("fetch")
    preview_row = MagicMock()
    mock_fetch.side_effect = [
        [{"row_count": 5}],
        [preview_row],
    ]

    validate_custom_query(
        _connection("oracle"), "demo", "SELECT * FROM t", preview_limit=1,
    )

    preview_sql = mock_fetch.call_args_list[1].args[1]
    assert "FETCH FIRST 1 ROWS ONLY" in preview_sql
    assert "LIMIT" not in preview_sql


@patch("testgen.common.custom_test_validation.fetch_from_target_db")
@patch("testgen.common.custom_test_validation.get_flavor_service")
def test_validate_custom_query_top_flavor_uses_prefix(mock_get_flavor, mock_fetch):
    mock_get_flavor.return_value = _flavor_service("top")
    preview_row = MagicMock()
    mock_fetch.side_effect = [
        [{"row_count": 5}],
        [preview_row],
    ]

    validate_custom_query(
        _connection("mssql"), "demo", "SELECT * FROM t", preview_limit=1,
    )

    preview_sql = mock_fetch.call_args_list[1].args[1]
    assert "TOP 1" in preview_sql
    assert "LIMIT" not in preview_sql


@patch("testgen.common.custom_test_validation.fetch_from_target_db")
@patch("testgen.common.custom_test_validation.get_flavor_service")
def test_validate_custom_query_propagates_db_errors(mock_get_flavor, mock_fetch):
    """DB errors propagate as-is — caller decides how to surface them."""
    mock_get_flavor.return_value = _flavor_service("limit")
    mock_fetch.side_effect = Exception("syntax error at or near 'DROP'")

    with pytest.raises(Exception, match="syntax error"):
        validate_custom_query(_connection(), "demo", "DROP TABLE orders")


# -- validate_metric_query ----------------------------------------------------

_SQL_METRIC_YAML = Path(testgen.__file__).parent / "template" / "dbsetup_test_types" / "test_types_SQL_Metric.yaml"


def _sql_metric_templates() -> dict[str, str]:
    doc = yaml.safe_load(_SQL_METRIC_YAML.read_text())["test_types"]
    return {row["sql_flavor"]: row["template"] for row in doc["test_templates"]}


@pytest.mark.parametrize("flavor", sorted(_sql_metric_templates()))
def test_render_metric_validation_query_fills_every_placeholder(flavor):
    query = render_metric_validation_query(
        _sql_metric_templates()[flavor], "demo", "SELECT COUNT(*) AS n FROM {DATA_SCHEMA}.orders"
    )
    assert not re.findall(r"\{[A-Z_]+\}", query)
    assert "demo.orders" in query


@pytest.mark.parametrize(
    ("metric_sql", "outcome"),
    [
        ("SELECT COUNT(*) AS n FROM t", 3),
        ("SELECT COUNT(*) AS n FROM t;\n", 3),
        ("SELECT MAX(n) AS n FROM t WHERE n > 5", InvalidMetricQuery),
        ("SELECT n FROM t WHERE n > 5", InvalidMetricQuery),
        ("SELECT n FROM t", duckdb.Error),
        ("SELECT 1 AS a, 2 AS b", duckdb.Error),
        ("SELECT 'abc' AS s", duckdb.Error),
    ],
)
@patch("testgen.common.custom_test_validation.fetch_from_target_db")
@patch("testgen.common.custom_test_validation.fetch_dict_from_db")
def test_validate_metric_query_runs_the_execution_template(mock_templates, mock_target, metric_sql, outcome):
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1), (2), (3)) v(n)")
    mock_templates.return_value = [{"template": _sql_metric_templates()["duckdb"]}]

    def run_on_duckdb(_connection, query, **_kwargs):
        cursor = con.execute(query)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    mock_target.side_effect = run_on_duckdb

    if isinstance(outcome, type) and issubclass(outcome, Exception):
        with pytest.raises(outcome):
            validate_metric_query(_connection("duckdb"), "main", metric_sql)
    else:
        assert validate_metric_query(_connection("duckdb"), "main", metric_sql) == outcome
