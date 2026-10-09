from unittest.mock import MagicMock, patch

import pytest

from testgen.common.data_catalog_service import TAG_FIELDS
from testgen.ui.views.data_catalog import get_excel_report_data, merge_tag_defaults

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
