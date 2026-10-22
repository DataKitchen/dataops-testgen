from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from testgen.common.models.data_table import (
    CatalogLevel,
    CatalogSource,
    CatalogTag,
    DataTable,
    TableCatalogSummary,
    catalog_tags_column,
    column_cde,
    effective_tag,
    parse_catalog_tags,
    table_cde,
)


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


def _compiled(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


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
def test_select_table_names_leaves_out_dropped_tables(session_mock):
    session_mock.return_value.scalars.return_value.all.return_value = []

    DataTable.select_table_names(table_groups_id=uuid4())

    assert "data_table_chars.drop_date IS NULL" in _compiled(session_mock.return_value.scalars.call_args[0][0])


@patch.object(DataTable, "_paginate", return_value=([], 0))
def test_list_for_table_group_leaves_out_dropped_tables_and_applies_clauses(paginate_mock):
    DataTable.list_for_table_group(
        DataTable.record_ct > 10, table_groups_id=uuid4(), page=2, limit=50,
    )

    query = paginate_mock.call_args.args[0]
    sql = _compiled(query)
    assert "data_table_chars.drop_date IS NULL" in sql
    assert "data_table_chars.record_ct > 10" in sql
    assert "JOIN table_groups ON table_groups.id = data_table_chars.table_groups_id" in sql
    assert "ORDER BY lower(data_table_chars.table_name)" in sql
    assert paginate_mock.call_args.kwargs == {
        "page": 2, "limit": 50, "data_class": TableCatalogSummary,
    }


def test_table_cde_reads_no_value_as_false():
    assert _compiled(select(table_cde())).startswith(
        "SELECT coalesce(data_table_chars.critical_data_element, false)"
    )


def test_column_cde_prefers_the_column_flag_over_the_table():
    assert "coalesce(data_column_chars.critical_data_element, data_table_chars.critical_data_element, false)" in (
        _compiled(select(column_cde()))
    )


@pytest.mark.parametrize(
    ("tag", "level", "expected"),
    [
        (
            "data_source", CatalogLevel.COLUMN,
            "coalesce(data_column_chars.data_source, data_table_chars.data_source, table_groups.data_source)",
        ),
        ("data_source", CatalogLevel.TABLE, "coalesce(data_table_chars.data_source, table_groups.data_source)"),
        (
            "aggregation_level", CatalogLevel.COLUMN,
            "coalesce(data_column_chars.aggregation_level, data_table_chars.aggregation_level)",
        ),
        ("aggregation_level", CatalogLevel.TABLE, "coalesce(data_table_chars.aggregation_level)"),
    ],
)
def test_effective_tag_inherits_column_then_table_then_table_group(tag, level, expected):
    assert expected in _compiled(select(effective_tag(tag, level)))


def test_catalog_tags_column_marks_where_each_value_comes_from():
    sql = _compiled(select(catalog_tags_column(CatalogLevel.COLUMN)))

    assert sql.startswith("SELECT jsonb_strip_nulls(jsonb_build_object('data_source', CASE")
    assert (
        "WHEN (data_column_chars.business_domain IS NOT NULL) "
        "THEN jsonb_build_array(data_column_chars.business_domain, CAST(NULL AS VARCHAR)) "
        "WHEN (data_table_chars.business_domain IS NOT NULL) "
        "THEN jsonb_build_array(data_table_chars.business_domain, CAST('table' AS VARCHAR)) "
        "WHEN (table_groups.business_domain IS NOT NULL) "
        "THEN jsonb_build_array(table_groups.business_domain, CAST('table group' AS VARCHAR)) END"
    ) in sql
    assert "table_groups.aggregation_level" not in sql


def test_parse_catalog_tags_orders_by_display_order_and_reads_the_source():
    tags = parse_catalog_tags({
        "data_classification": ["Confidential", None],
        "business_domain": ["Finance", "table group"],
        "transform_level": ["Gold", "table"],
    })

    assert tags == [
        CatalogTag("business_domain", "Business domain", "Finance", CatalogSource.TABLE_GROUP),
        CatalogTag("transform_level", "Transform level", "Gold", CatalogSource.TABLE),
        CatalogTag("data_classification", "Data classification", "Confidential", None),
    ]


def test_parse_catalog_tags_without_values():
    assert parse_catalog_tags(None) == []
    assert parse_catalog_tags({}) == []
