"""Tests for ScoreDefinition.as_score_card() filter behavior across toggle combinations.

Covers TG-1078: in CDE-only mode (total_score OFF, cde_score ON) the per-category
scores must be computed over CDE columns only. In all other modes the per-category
scores must be computed over the full column universe (no CDE filter).
"""

from unittest.mock import MagicMock, patch

import pytest

from testgen.common.models.scores import (
    ScoreCategory,
    ScoreDefinition,
    ScoreDefinitionCriteria,
    ScoreDefinitionFilter,
)

pytestmark = pytest.mark.unit


CDE_FILTER_FRAGMENT = "critical_data_element = true"


def _make_definition(
    *,
    total_score: bool,
    cde_score: bool,
    category: ScoreCategory = ScoreCategory.dq_dimension,
) -> ScoreDefinition:
    definition = ScoreDefinition(
        project_code="demo",
        name="Test card",
        total_score=total_score,
        cde_score=cde_score,
        category=category,
    )
    definition.criteria = ScoreDefinitionCriteria(
        operand="AND",
        group_by_field=True,
        filters=[ScoreDefinitionFilter(field="table_groups_name", value="my_group")],
    )
    return definition


def _capture_executed_sql(definition: ScoreDefinition) -> list[str]:
    """Run as_score_card() against a mocked session and return the SQL of each execute call."""
    session = MagicMock()
    mappings_result = MagicMock()
    mappings_result.first.return_value = {}
    mappings_result.all.return_value = []
    session.execute.return_value.mappings.return_value = mappings_result

    with patch("testgen.common.models.scores.get_current_session", return_value=session):
        definition.as_score_card()

    return [str(call.args[0]) for call in session.execute.call_args_list]


@pytest.mark.parametrize(
    "category",
    [ScoreCategory.dq_dimension, ScoreCategory.impact_dimension, ScoreCategory.business_domain],
)
def test_categories_query_omits_cde_filter_in_total_only_mode(category):
    definition = _make_definition(total_score=True, cde_score=False, category=category)
    sql_calls = _capture_executed_sql(definition)

    assert len(sql_calls) == 2, "expected one overall and one categories query"
    overall_sql, categories_sql = sql_calls
    assert CDE_FILTER_FRAGMENT not in categories_sql
    assert CDE_FILTER_FRAGMENT not in overall_sql


@pytest.mark.parametrize(
    "category",
    [ScoreCategory.dq_dimension, ScoreCategory.impact_dimension, ScoreCategory.business_domain],
)
def test_categories_query_omits_cde_filter_in_total_and_cde_mode(category):
    definition = _make_definition(total_score=True, cde_score=True, category=category)
    sql_calls = _capture_executed_sql(definition)

    assert len(sql_calls) == 2
    overall_sql, categories_sql = sql_calls
    assert CDE_FILTER_FRAGMENT not in categories_sql
    assert CDE_FILTER_FRAGMENT not in overall_sql


@pytest.mark.parametrize(
    "category",
    [ScoreCategory.dq_dimension, ScoreCategory.impact_dimension, ScoreCategory.business_domain],
)
def test_categories_query_includes_cde_filter_in_cde_only_mode(category):
    definition = _make_definition(total_score=False, cde_score=True, category=category)
    sql_calls = _capture_executed_sql(definition)

    assert len(sql_calls) == 2
    overall_sql, categories_sql = sql_calls
    assert CDE_FILTER_FRAGMENT in categories_sql, (
        "Categories query must filter by CDE columns when the card is in CDE-only mode"
    )
    # Overall query must stay un-filtered by CDE — it selects score and cde_score as
    # separate columns, so adding the filter would zero out the non-CDE total.
    assert CDE_FILTER_FRAGMENT not in overall_sql


def test_categories_query_uses_column_template_for_column_category():
    definition = _make_definition(total_score=False, cde_score=True, category=ScoreCategory.business_domain)
    sql_calls = _capture_executed_sql(definition)

    categories_sql = sql_calls[1]
    # Column-grouped template aggregates by a placeholder substituted into the SELECT.
    assert "business_domain" in categories_sql
    assert CDE_FILTER_FRAGMENT in categories_sql
