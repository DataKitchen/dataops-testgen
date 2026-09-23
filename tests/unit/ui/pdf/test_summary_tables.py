"""The schema row of the issue report summary tables, across database types."""

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.ui.pdf import hygiene_issue_report, test_result_report

pytestmark = pytest.mark.unit

TAG_COLUMNS = {
    "data_source": None,
    "source_system": None,
    "source_process": None,
    "business_domain": None,
    "stakeholder_group": None,
    "transform_level": None,
    "aggregation_level": None,
    "data_product": None,
    "data_classification": None,
}

DOCUMENT = SimpleNamespace(width=500)

# Row holding the schema in each summary table; its label and value are that row's first two cells.
HYGIENE_SCHEMA_ROW = 3
TEST_RESULT_SCHEMA_ROW = 4


def _hygiene_issue():
    return {
        "issue_likelihood": "Definite",
        "anomaly_name": "Suggested Primary Key",
        "anomaly_description": "Column looks like a primary key",
        "detail": "Distinct values: 1000",
        "profiling_starttime": None,
        "table_groups_name": "tg",
        "table_groups_id": str(uuid4()),
        "schema_name": "main",
        "db_data_type": "VARCHAR",
        "table_name": "orders",
        "functional_data_type": "ID",
        "column_name": "order_id",
        "impact_dimension": "Reliability",
        "disposition": None,
        "dq_dimension": "Uniqueness",
        "critical_data_element": False,
        "pii_flag": None,
        "column_description": None,
        "job_execution_id": str(uuid4()),
        "id": str(uuid4()),
        "project_code": "P",
        **TAG_COLUMNS,
    }


def _test_result():
    return {
        "result_status": "Failed",
        "test_name_short": "Unique",
        "test_name_long": "Unique Values",
        "test_description": "Checks for duplicates",
        "result_measure": "3",
        "measure_uom_description": "Duplicate values",
        "threshold_value": "0",
        "threshold_description": "Maximum duplicates",
        "test_date": None,
        "test_suite": "ts",
        "table_groups_name": "tg",
        "table_groups_id": str(uuid4()),
        "schema_name": "main",
        "table_name": "orders",
        "impact_dimension": "Reliability",
        "column_names": "order_id",
        "dq_dimension": "Uniqueness",
        "disposition": None,
        "critical_data_element": False,
        "pii_flag": None,
        "column_description": None,
        "job_execution_id": str(uuid4()),
        "test_result_id": str(uuid4()),
        "project_code": "P",
        **TAG_COLUMNS,
    }


def _hygiene_schema_cells(schema_label):
    with patch.object(hygiene_issue_report, "schema_label_for_table_group", return_value=schema_label):
        table = hygiene_issue_report.build_summary_table(DOCUMENT, _hygiene_issue())
    table.wrapOn(None, DOCUMENT.width, 700)
    return table._cellvalues[HYGIENE_SCHEMA_ROW][:2]


def _test_result_schema_cells(schema_label):
    with patch.object(test_result_report, "schema_label_for_table_group", return_value=schema_label):
        table = test_result_report.build_summary_table(DOCUMENT, _test_result())
    table.wrapOn(None, DOCUMENT.width, 700)
    return table._cellvalues[TEST_RESULT_SCHEMA_ROW][:2]


@pytest.mark.parametrize("schema_cells", (_hygiene_schema_cells, _test_result_schema_cells))
@pytest.mark.parametrize(
    ("schema_label", "expected"),
    (
        ("Schema", ["Schema", "main"]),
        ("Data Space", ["Data Space", "main"]),
        (None, ["", ""]),
    ),
)
def test_schema_row_follows_the_database_type(schema_cells, schema_label, expected):
    assert schema_cells(schema_label) == expected
