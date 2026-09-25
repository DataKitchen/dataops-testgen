"""The preview cache key has to cover every field that changes what the preview finds."""

import pytest

from testgen.common.models.table_group import TableGroup
from testgen.ui.queries.table_group_queries import preview_cache_key

pytestmark = pytest.mark.unit


def _table_group(**overrides) -> TableGroup:
    defaults = {
        "table_groups_name": "Claims",
        "table_group_schema": "main",
        "profiling_table_set": None,
        "profiling_include_mask": None,
        "profiling_exclude_mask": None,
        "file_declarations": [{"name": "claims", "uri": "claims_2024.csv", "format": "csv"}],
    }
    return TableGroup(**{**defaults, **overrides})


def test_the_same_table_group_keys_the_same():
    assert preview_cache_key(_table_group()) == preview_cache_key(_table_group())


@pytest.mark.parametrize("field", [
    "table_group_schema",
    "profiling_table_set",
    "profiling_include_mask",
    "profiling_exclude_mask",
])
def test_editing_a_criteria_field_changes_the_key(field):
    assert preview_cache_key(_table_group()) != preview_cache_key(_table_group(**{field: "changed"}))


@pytest.mark.parametrize("declarations", [
    [{"name": "claims", "uri": "claims_2025.csv", "format": "csv"}],
    [{"name": "renamed", "uri": "claims_2024.csv", "format": "csv"}],
    [{"name": "claims", "uri": "claims_2024.csv", "format": "parquet"}],
    [{"name": "claims", "uri": "claims_2024.csv", "format": "csv", "options": {"delimiter": "|"}}],
    [
        {"name": "claims", "uri": "claims_2024.csv", "format": "csv"},
        {"name": "members", "uri": "members.csv", "format": "csv"},
    ],
    [],
    None,
])
def test_editing_the_declarations_changes_the_key(declarations):
    assert preview_cache_key(_table_group()) != preview_cache_key(_table_group(file_declarations=declarations))


def test_the_key_is_hashable():
    """Streamlit hashes whatever the function returns, and a list of dicts would raise."""
    assert hash(preview_cache_key(_table_group())) is not None
