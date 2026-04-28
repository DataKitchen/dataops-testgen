from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common.models.test_definition import TestDefinition, TestDefinitionSummary

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clear_streamlit_cache():
    TestDefinition._paginate.clear()
    yield


def _make_row(table_name: str = "my_table", total_count: int = 10) -> dict:
    """Return a minimal row dict as returned by session.execute().mappings().all()."""
    return {
        # TestDefinitionSummary fields
        "id": uuid4(),
        "table_groups_id": uuid4(),
        "profile_run_id": uuid4(),
        "test_type": "CUSTOM",
        "test_suite_id": uuid4(),
        "test_description": None,
        "schema_name": "public",
        "table_name": table_name,
        "column_name": "col1",
        "skip_errors": 0,
        "baseline_ct": None,
        "baseline_unique_ct": None,
        "baseline_value": None,
        "baseline_value_ct": None,
        "threshold_value": None,
        "baseline_sum": None,
        "baseline_avg": None,
        "baseline_sd": None,
        "lower_tolerance": None,
        "upper_tolerance": None,
        "subset_condition": None,
        "groupby_names": None,
        "having_condition": None,
        "window_date_column": None,
        "window_days": None,
        "match_schema_name": None,
        "match_table_name": None,
        "match_column_names": None,
        "match_subset_condition": None,
        "match_groupby_names": None,
        "match_having_condition": None,
        "custom_query": None,
        "history_calculation": None,
        "history_calculation_upper": None,
        "history_lookback": None,
        "test_active": True,
        "test_definition_status": None,
        "severity": None,
        "lock_refresh": False,
        "last_auto_gen_date": None,
        "profiling_as_of_date": None,
        "last_manual_update": datetime.now(),
        "export_to_observability": False,
        "prediction": None,
        "flagged": False,
        # TestTypeSummary fields
        "test_name_short": "Custom",
        "default_test_description": "A test",
        "measure_uom": "",
        "measure_uom_description": "",
        "default_parm_columns": "",
        "default_parm_prompts": "",
        "default_parm_help": "",
        "default_parm_required": "",
        "default_severity": "Warning",
        "test_scope": "column",
        "dq_dimension": "",
        "usage_notes": "",
        # Window function extra column
        "total_count": total_count,
    }


@patch("testgen.common.models.test_definition.get_current_session")
def test__paginate_returns_items_and_total(mock_get_session):
    rows = [_make_row("table_a", total_count=3), _make_row("table_b", total_count=3), _make_row("table_c", total_count=3)]
    mock_get_session.return_value.execute.return_value.mappings.return_value.all.return_value = rows

    items, total = TestDefinition._paginate()

    assert total == 3
    assert len(items) == 3
    assert all(isinstance(item, TestDefinitionSummary) for item in items)
    assert items[0].table_name == "table_a"
    assert items[2].table_name == "table_c"


@patch("testgen.common.models.test_definition.get_current_session")
def test__paginate_empty_result_returns_zero_total(mock_get_session):
    mock_get_session.return_value.execute.return_value.mappings.return_value.all.return_value = []

    items, total = TestDefinition._paginate()

    assert items == []
    assert total == 0


@patch("testgen.common.models.test_definition.get_current_session")
def test__paginate_total_count_not_in_item_fields(mock_get_session):
    mock_get_session.return_value.execute.return_value.mappings.return_value.all.return_value = [_make_row()]

    items, _ = TestDefinition._paginate()

    assert not hasattr(items[0], "total_count")


@patch("testgen.common.models.test_definition.get_current_session")
def test__paginate_uses_correct_offset_and_limit(mock_get_session):
    mock_get_session.return_value.execute.return_value.mappings.return_value.all.return_value = []

    TestDefinition._paginate(page_index=2, page_size=100)

    call_args = mock_get_session.return_value.execute.call_args
    query = call_args[0][0]
    compiled = query.compile(compile_kwargs={"literal_binds": True})
    sql = str(compiled)

    assert "LIMIT 100" in sql
    assert "OFFSET 200" in sql


@patch("testgen.common.models.test_definition.get_current_session")
def test__paginate_page_zero_has_no_offset(mock_get_session):
    mock_get_session.return_value.execute.return_value.mappings.return_value.all.return_value = []

    TestDefinition._paginate(page_index=0, page_size=500)

    call_args = mock_get_session.return_value.execute.call_args
    query = call_args[0][0]
    compiled = query.compile(compile_kwargs={"literal_binds": True})
    sql = str(compiled)

    assert "LIMIT 500" in sql
    assert "OFFSET 0" in sql
