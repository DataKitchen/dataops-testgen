import pytest

from testgen.ui.views.data_catalog import merge_tag_defaults

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
