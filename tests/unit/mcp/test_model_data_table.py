from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from testgen.common.models.data_table import DataTable


def test_default_order_by_compiles_for_entity_select():
    # Regression: the inherited Entity default ordered by the textual label "id", which
    # fails to compile here because the PK column is "table_id". A full-entity select
    # (e.g. DataTable.select_where) must compile and order by a real column.
    stmt = select(DataTable).order_by(*DataTable._default_order_by)
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ORDER BY" in compiled
    assert "table_name" in compiled

_CATALOG_METADATA_COLUMNS = {
    "description",
    "data_source",
    "source_system",
    "source_process",
    "business_domain",
    "stakeholder_group",
    "transform_level",
    "aggregation_level",
    "data_product",
    "data_classification",
}


def test_catalog_metadata_columns_are_mapped():
    mapped = set(DataTable.__table__.columns.keys())
    assert _CATALOG_METADATA_COLUMNS <= mapped


def test_catalog_metadata_attributes_settable():
    table = DataTable()
    table.description = "Customer master table"
    table.business_domain = "Sales"
    assert table.description == "Customer master table"
    assert table.business_domain == "Sales"


@patch("testgen.common.models.data_table.get_current_session")
def test_select_table_names_returns_list(session_mock):
    session_mock.return_value.scalars.return_value.all.return_value = ["customers", "orders", "products"]

    result = DataTable.select_table_names(table_groups_id=uuid4())

    assert result == ["customers", "orders", "products"]
    session_mock.return_value.scalars.assert_called_once()


@patch("testgen.common.models.data_table.get_current_session")
def test_select_table_names_empty(session_mock):
    session_mock.return_value.scalars.return_value.all.return_value = []

    result = DataTable.select_table_names(table_groups_id=uuid4())

    assert result == []


@patch("testgen.common.models.data_table.get_current_session")
def test_count_tables(session_mock):
    session_mock.return_value.scalar.return_value = 42

    result = DataTable.count_tables(table_groups_id=uuid4())

    assert result == 42


@patch("testgen.common.models.data_table.get_current_session")
def test_count_tables_none_returns_zero(session_mock):
    session_mock.return_value.scalar.return_value = None

    result = DataTable.count_tables(table_groups_id=uuid4())

    assert result == 0
