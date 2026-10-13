from unittest.mock import MagicMock, patch

import pytest

from testgen.common.data_catalog_service import TAG_FIELDS
from testgen.ui.queries.data_catalog_queries import CatalogFilters
from testgen.ui.views.data_catalog import (
    catalog_filter_params,
    catalog_filters_from_params,
    get_catalog_page_number,
    get_excel_report_data,
    merge_tag_defaults,
)

VIEW_MODULE = "testgen.ui.views.data_catalog"

pytestmark = pytest.mark.unit


class Test_MergeTagDefaults:
    def test_db_value_beats_matching_seed_case_insensitively(self):
        values = {"data_classification": ["confidential", "public"]}
        defaults = {"data_classification": ["Confidential", "Internal", "Public", "Restricted"]}
        result = merge_tag_defaults(values, defaults)
        assert result["data_classification"] == ["confidential", "Internal", "public", "Restricted"]

    def test_seed_added_when_no_db_match(self):
        values = {"data_classification": []}
        defaults = {"data_classification": ["Confidential", "Internal", "Public", "Restricted"]}
        result = merge_tag_defaults(values, defaults)
        assert result["data_classification"] == ["Confidential", "Internal", "Public", "Restricted"]

    def test_result_sorted_case_insensitively(self):
        values = {"data_classification": ["RESTRICTED"]}
        defaults = {"data_classification": ["Confidential", "Internal", "Public", "Restricted"]}
        result = merge_tag_defaults(values, defaults)
        assert result["data_classification"] == ["Confidential", "Internal", "Public", "RESTRICTED"]

    def test_non_classified_tags_unaffected(self):
        values = {"data_product": ["prod-a"], "data_classification": ["internal"]}
        defaults = {"data_classification": ["Confidential", "Internal", "Public", "Restricted"]}
        result = merge_tag_defaults(values, defaults)
        assert result["data_product"] == ["prod-a"]
        assert "Internal" not in result["data_classification"]
        assert "internal" in result["data_classification"]

    def test_empty_db_values_for_tagged_field(self):
        values = {}
        defaults = {"data_classification": ["Confidential"]}
        result = merge_tag_defaults(values, defaults)
        assert result["data_classification"] == ["Confidential"]


def test_an_export_of_tables_alone_has_every_column_of_the_report():
    table_group = MagicMock(id="tg-1", table_groups_name="sales")
    table_row = {"table_name": "orders", "critical_data_element": True, "data_source": "erp", "add_date": None}
    for tag in TAG_FIELDS:
        table_row.setdefault(tag, None)
    captured = {}

    def fake_excel(data, *_args, columns, **_kwargs):
        captured["frame"] = data[list(columns)]

    with (
        patch(f"{VIEW_MODULE}.get_tables_by_id", return_value=[table_row]),
        patch(f"{VIEW_MODULE}.get_columns_by_id") as mock_columns,
        patch(f"{VIEW_MODULE}.schema_label_for_table_group", return_value=None),
        patch(f"{VIEW_MODULE}.session") as mock_session,
        patch(f"{VIEW_MODULE}.get_excel_file_data", side_effect=fake_excel),
    ):
        mock_session.auth.user_has_permission.return_value = True
        get_excel_report_data(lambda *_: None, table_group, [{"type": "table", "id": "t-1"}])

    mock_columns.assert_not_called()
    assert captured["frame"]["table_name"].tolist() == ["orders"]
    assert captured["frame"]["critical_data_element"].tolist() == ["Yes"]


def _url_params(filters: CatalogFilters) -> dict[str, str]:
    """The parameters left in the URL: the router drops the ones set to None."""
    return {key: value for key, value in catalog_filter_params(filters).items() if value is not None}


def test_default_catalog_filters_leave_nothing_in_the_url():
    assert _url_params(CatalogFilters()) == {}
    assert catalog_filters_from_params({}) == CatalogFilters()


@pytest.mark.parametrize(
    "filters",
    [
        CatalogFilters(search="orders", search_columns=False),
        CatalogFilters(search="amount", search_tables=False),
        CatalogFilters(critical_data_element=True, pii_flag=True, show_excluded=True),
        CatalogFilters(tags=(("data_product", "Sales"), ("data_source", "ERP"))),
    ],
)
def test_catalog_filters_survive_the_url(filters):
    assert catalog_filters_from_params(_url_params(filters)) == filters


def test_catalog_filter_params_clear_every_tag_not_set():
    params = catalog_filter_params(CatalogFilters(tags=(("data_source", "ERP"),)))
    assert {tag: params[tag] for tag in TAG_FIELDS} == {tag: "ERP" if tag == "data_source" else None for tag in TAG_FIELDS}


@pytest.mark.parametrize(("page", "expected"), [("3", 3), ("0", 0), ("-1", 0), ("x", 0), (["1", "2"], 0)])
def test_catalog_page_number_comes_from_the_page_parameter(page, expected):
    with patch(f"{VIEW_MODULE}.get_catalog_page_of_item") as page_of_item:
        assert get_catalog_page_number("tg", CatalogFilters(), page, "table_abc") == expected
    page_of_item.assert_not_called()


def test_catalog_page_number_without_a_page_shows_the_selected_item():
    with patch(f"{VIEW_MODULE}.get_catalog_page_of_item", return_value=4) as page_of_item:
        assert get_catalog_page_number("tg", CatalogFilters(), None, "column_abc_def") == 4
    page_of_item.assert_called_once_with("tg", CatalogFilters(), "column", "abc_def")
    assert get_catalog_page_number("tg", CatalogFilters(), None, None) == 0
