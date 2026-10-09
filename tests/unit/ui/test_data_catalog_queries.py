from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.ui.queries.data_catalog_queries import (
    CATALOG_PAGE_SIZE,
    CatalogFilters,
    _visibility_ctes,
    get_catalog_page,
    get_catalog_page_of_item,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.queries.data_catalog_queries"
TABLE_GROUP_ID = str(uuid4())


def test_filters_drop_unknown_tags_so_none_reach_the_sql():
    filters = CatalogFilters.from_dict({"tags": {"data_source": "erp", "1=1; DROP TABLE x": "y", "data_product": None}})

    assert filters.tags == (("data_source", "erp"),)


def test_filters_search_both_names_when_neither_is_chosen():
    filters = CatalogFilters.from_dict({"search": "cust", "search_tables": False, "search_columns": False})

    assert (filters.search_tables, filters.search_columns) == (True, True)


def test_filters_round_trip_through_a_dict():
    filters = CatalogFilters.from_dict({
        "search": " cust ", "search_tables": False, "critical_data_element": True, "tags": {"data_source": "erp"},
    })

    assert CatalogFilters.from_dict(filters.to_dict()) == filters
    assert filters.search == "cust"


def test_no_filters_show_every_table_and_every_column_but_excluded_ones():
    ctes, params = _visibility_ctes(TABLE_GROUP_ID, CatalogFilters())

    assert "(c.excluded_data_element IS NOT TRUE) AS visible" in ctes
    assert "(TRUE) OR cv.any_visible AS visible" in ctes
    assert params == {"table_group_id": TABLE_GROUP_ID}


def test_the_column_scan_is_inlined_so_a_page_reads_only_its_tables():
    ctes, _ = _visibility_ctes(TABLE_GROUP_ID, CatalogFilters())

    assert "catalog_columns AS NOT MATERIALIZED (" in ctes


def test_search_matches_names_as_plain_substrings():
    ctes, params = _visibility_ctes(TABLE_GROUP_ID, CatalogFilters(search="Cust_", show_excluded=True))

    assert params["search"] == "cust_"
    assert "POSITION(:search IN LOWER(c.column_name)) > 0" in ctes
    assert "POSITION(:search IN LOWER(t.table_name)) > 0" in ctes
    assert "LIKE" not in ctes


def test_search_limited_to_tables_shows_no_column_on_its_own():
    ctes, _ = _visibility_ctes(TABLE_GROUP_ID, CatalogFilters(search="cust", search_columns=False, show_excluded=True))

    assert "(FALSE) AS visible" in ctes


def test_the_pii_filter_matches_no_table_on_its_own():
    ctes, _ = _visibility_ctes(TABLE_GROUP_ID, CatalogFilters(pii_flag=True, show_excluded=True))

    assert "(FALSE) OR cv.any_visible" in ctes
    assert "NULLIF(c.pii_flag, '') IS NOT NULL" in ctes


@pytest.mark.parametrize(
    ("tag", "column_value", "table_value"),
    [
        ("data_source", "COALESCE(c.data_source, t.data_source, tg.data_source)", "COALESCE(t.data_source, tg.data_source)"),
        ("aggregation_level", "COALESCE(c.aggregation_level, t.aggregation_level)", "COALESCE(t.aggregation_level)"),
    ],
)
def test_tag_filters_match_the_inherited_value(tag, column_value, table_value):
    ctes, params = _visibility_ctes(TABLE_GROUP_ID, CatalogFilters(tags=((tag, "erp"),), show_excluded=True))

    assert f"({column_value} = :tag_0) AS visible" in ctes
    assert f"({table_value} = :tag_0) OR cv.any_visible" in ctes
    assert params["tag_0"] == "erp"


def test_a_page_reads_only_its_tables_columns():
    table_ids = [str(uuid4()), str(uuid4())]
    responses = [
        [{"total_count": 250, "visible_count": 120}],
        [{"table_id": f"table_{table_id}", "table_name": f"t{index}"} for index, table_id in enumerate(table_ids)],
        [{"column_id": "column_1", "table_id": f"table_{table_ids[0]}"}],
    ]
    with patch(f"{MODULE}.fetch_all_from_db", side_effect=responses) as mock_fetch:
        page = get_catalog_page.__wrapped__(TABLE_GROUP_ID, CatalogFilters(), 1)

    assert page["visible_count"] == 120
    assert page["total_count"] == 250
    assert page["page"] == 1
    assert len(page["tables"]) == 2
    assert mock_fetch.call_args_list[1].args[1]["offset"] == CATALOG_PAGE_SIZE
    assert mock_fetch.call_args_list[2].args[1]["table_ids"] == table_ids


def test_an_empty_page_skips_the_columns_query():
    responses = [[{"total_count": 0, "visible_count": 0}], []]
    with patch(f"{MODULE}.fetch_all_from_db", side_effect=responses) as mock_fetch:
        page = get_catalog_page.__wrapped__(TABLE_GROUP_ID, CatalogFilters(), 0)

    assert page["tables"] == [] and page["columns"] == []
    assert mock_fetch.call_count == 2


@pytest.mark.parametrize(("preceding", "expected"), [(0, 0), (CATALOG_PAGE_SIZE - 1, 0), (CATALOG_PAGE_SIZE, 1)])
def test_an_item_opens_on_the_page_that_shows_its_table(preceding, expected):
    with patch(f"{MODULE}.fetch_all_from_db", return_value=[{"selected_visible": True, "preceding_count": preceding}]):
        assert get_catalog_page_of_item(TABLE_GROUP_ID, CatalogFilters(), "column", str(uuid4())) == expected


def test_an_item_the_filters_hide_has_no_page():
    with patch(f"{MODULE}.fetch_all_from_db", return_value=[{"selected_visible": None, "preceding_count": 0}]):
        assert get_catalog_page_of_item(TABLE_GROUP_ID, CatalogFilters(), "table", str(uuid4())) is None
