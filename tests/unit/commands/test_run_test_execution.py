"""Tests for ``run_test_execution``'s run-scoped referential retargeting."""

from uuid import uuid4

import pytest

from testgen.commands.queries.execute_tests_query import TestExecutionDef
from testgen.commands.run_test_execution import retarget_match_schema

pytestmark = pytest.mark.unit


def _td(**overrides) -> TestExecutionDef:
    defaults = {
        "id": uuid4(), "test_type": "Combo_Match", "schema_name": "staging_a",
        "table_name": "orders", "column_name": "customer_id", "lock_refresh": "N",
        "skip_errors": 0, "history_calculation": "NONE", "custom_query": "", "prediction": None,
        "run_type": "CAT", "test_scope": "referential", "template": "", "measure": "COUNT(*)",
        "test_operator": ">=", "test_condition": "0",
        "baseline_ct": "", "baseline_unique_ct": "", "baseline_value": "", "baseline_value_ct": "",
        "threshold_value": "", "baseline_sum": "", "baseline_avg": "", "baseline_sd": "",
        "lower_tolerance": "", "upper_tolerance": "", "subset_condition": "", "groupby_names": "",
        "having_condition": "", "window_date_column": "", "window_days": "",
        "match_schema_name": "", "match_table_name": "", "match_column_names": "",
        "match_subset_condition": "", "match_groupby_names": "", "match_having_condition": "",
    }
    defaults.update(overrides)
    return TestExecutionDef(**defaults)


def test_retargets_the_match_schema_of_a_referential_test():
    test_def = _td(match_schema_name="staging_a", match_table_name="order_totals")

    retarget_match_schema([test_def], "reference_2026_09_11")

    assert test_def.match_schema_name == "reference_2026_09_11"


def test_leaves_the_table_group_schema_alone():
    """Where the table group's own data lives is the table group's to say, not a run's."""
    test_defs = [_td(schema_name="staging_a"), _td(schema_name="staging_a", table_name="customers")]

    retarget_match_schema(test_defs, "reference_2026_09_11")

    assert [td.schema_name for td in test_defs] == ["staging_a"] * 2


@pytest.mark.parametrize("empty", ["", None])
def test_leaves_an_unset_match_schema_unset(empty):
    """An absent match schema means no referential target. Filling one in would turn a test
    validation reports as incomplete into one that silently compares against the wrong table."""
    test_def = _td(match_schema_name=empty)

    retarget_match_schema([test_def], "reference_2026_09_11")

    assert test_def.match_schema_name == empty


def test_leaves_the_stored_definition_fields_it_does_not_own():
    test_def = _td(match_schema_name="staging_a", table_name="orders", match_table_name="totals")

    retarget_match_schema([test_def], "reference_2026_09_11")

    assert test_def.table_name == "orders"
    assert test_def.match_table_name == "totals"
