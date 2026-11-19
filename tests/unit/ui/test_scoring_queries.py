import dataclasses
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import sqlglot
from sqlglot import exp

from testgen.commands.queries.execute_tests_query import InputParameters, TestExecutionSQL
from testgen.common.database.database_service import get_flavor_service
from testgen.common.source_data_service import LookupData, _build_query_standard
from testgen.ui.queries.scoring_queries import get_score_card_issue_reports

pytestmark = pytest.mark.unit

SOURCE_DATA_MODULE = "testgen.common.source_data_service"


def _run_input_parameters(**values: str) -> str:
    """Build an ``input_parameters`` value with the writer that test execution uses."""
    fields = {field.name: "" for field in dataclasses.fields(InputParameters)}
    fields.update(values)
    test_def = SimpleNamespace(param_columns=set(), **fields)
    writer = SimpleNamespace(flavor_service=get_flavor_service("postgresql"))
    return TestExecutionSQL._get_input_parameters(writer, test_def)


# A test result's columns as test execution writes them, for a run that overrode the match table.
_STORED_RESULT = {
    "project_code": "DEFAULT",
    "id": "8c1f7f0e-4c5e-4a43-9a52-6a0f0f6b2b11",
    "test_type": "Aggregate_Balance",
    "test_type_id": "1500",
    "test_definition_id": "0f8f0f6b-2b11-4c5e-9a52-8c1f7f0e4a43",
    "table_groups_id": "6a0f0f6b-2b11-4c5e-9a52-8c1f7f0e4a43",
    "test_run_id": "2b116a0f-0f6b-4c5e-9a52-8c1f7f0e4a43",
    "schema_name": "demo",
    "table_name": "orders",
    "column_names": "amount",
    "column_type": "numeric",
    "test_time": "2026-11-18 10:30:45",
    "input_parameters": _run_input_parameters(match_schema_name="build_20261118", match_table_name="orders_snapshot"),
}


def _fake_fetch_all_from_db(query: str, params: dict) -> list[dict]:
    """Return one row shaped by the query's select list, read from the stored test result."""
    select = sqlglot.parse_one(query, dialect="postgres").find(exp.Select)
    row = {}
    for column in select.expressions:
        source = column.unalias()
        stored_name = source.name if isinstance(source, exp.Column) else column.alias_or_name
        row[column.alias_or_name] = _STORED_RESULT.get(stored_name)
    return [row]


@patch(f"{SOURCE_DATA_MODULE}._run_variables", return_value=None)
@patch(f"{SOURCE_DATA_MODULE}.replace_templated_functions", side_effect=lambda query, _flavor: query)
@patch(f"{SOURCE_DATA_MODULE}.DataTable.list_column_chars", return_value=[])
@patch(f"{SOURCE_DATA_MODULE}.TestDefinition.get_for_project")
@patch(f"{SOURCE_DATA_MODULE}._get_lookup_data")
@patch("testgen.ui.queries.scoring_queries.fetch_all_from_db", side_effect=_fake_fetch_all_from_db)
def test_issue_report_source_data_reads_the_runs_match_table(_fetch, get_lookup_data, get_test_definition, *_):
    get_lookup_data.return_value = LookupData(
        lookup_query="SELECT * FROM {MATCH_SCHEMA_NAME}.{MATCH_TABLE_NAME}",
        sql_flavor="postgresql",
    )
    get_test_definition.return_value = SimpleNamespace(
        **{
            **{field.name: None for field in dataclasses.fields(InputParameters)},
            "test_type": "Aggregate_Balance",
            "match_schema_name": "stored_schema",
            "match_table_name": "stored_table",
        }
    )

    [issue] = get_score_card_issue_reports([{"id": _STORED_RESULT["id"], "issue_type": "test"}])
    lookup_query = _build_query_standard(issue, limit=500)

    assert "build_20261118.orders_snapshot" in lookup_query
    assert "stored_schema" not in lookup_query
