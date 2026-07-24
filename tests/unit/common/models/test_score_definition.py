"""Tests for ScoreDefinition.as_score_card() filter behavior across toggle combinations.

Covers TG-1078: in CDE-only mode (total_score OFF, cde_score ON) the per-category
scores must be computed over CDE columns only. In all other modes the per-category
scores must be computed over the full column universe (no CDE filter).
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

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


def _make_project_wide_definition(*, category: ScoreCategory | None = None) -> ScoreDefinition:
    definition = ScoreDefinition(
        project_code="demo",
        name="Project-wide card",
        total_score=True,
        cde_score=True,
        category=category,
    )
    definition.criteria = ScoreDefinitionCriteria(operand="AND", group_by_field=True, filters=[])
    return definition


def test_as_score_card_runs_when_criteria_has_no_filters():
    """With no attribute filters, `as_score_card` still runs the project-wide query."""
    definition = _make_project_wide_definition()
    sql_calls = _capture_executed_sql(definition)

    assert len(sql_calls) == 1, "expected only the overall query when no category is set"
    overall_sql = sql_calls[0]
    assert "project_code = 'demo'" in overall_sql
    assert CDE_FILTER_FRAGMENT not in overall_sql


def test_as_score_card_no_filters_still_runs_category_query():
    """Category breakdown query runs on project-wide criteria too."""
    definition = _make_project_wide_definition(category=ScoreCategory.impact_dimension)
    sql_calls = _capture_executed_sql(definition)

    assert len(sql_calls) == 2
    _, categories_sql = sql_calls
    assert "project_code = 'demo'" in categories_sql


def test_get_raw_query_filters_omits_criteria_when_no_filters():
    """`_get_raw_query_filters` drops the criteria SQL when there are no filters."""
    definition = _make_project_wide_definition()

    parts = definition._get_raw_query_filters()
    assert parts == ["project_code = 'demo'"]

    parts_cde = definition._get_raw_query_filters(cde_only=True)
    assert parts_cde == ["project_code = 'demo'", "critical_data_element = true"]


def test_get_raw_query_filters_applies_prefix_uniformly():
    """Prefix wraps every clause, including when criteria is empty."""
    definition = _make_project_wide_definition()

    parts = definition._get_raw_query_filters(prefix="tr.")
    assert parts == ["tr.project_code = 'demo'"]


# --- list_with_table_group_targets ---


def _row(definition_id, name, tg_names):
    """Simulate a row returned by the recursive-CTE aggregate query."""
    row = MagicMock()
    row.id = definition_id
    row.name = name
    row.tg_names = tg_names
    return row


@patch("testgen.common.models.scores.get_current_session")
def test_list_with_table_group_targets_single_name_filter(mock_session_fn):
    """A scorecard with one table_groups_name filter yields (id, name, [tg_name])."""
    def_id = uuid4()
    mock_result = MagicMock()
    mock_result.all.return_value = [_row(def_id, "orders-sc", ["orders"])]
    mock_session_fn.return_value.execute.return_value = mock_result

    out = ScoreDefinition.list_with_table_group_targets("proj")

    assert out == [(def_id, "orders-sc", ["orders"])]


@patch("testgen.common.models.scores.get_current_session")
def test_list_with_table_group_targets_multiple_name_filters(mock_session_fn):
    """A scorecard with multiple table_groups_name filters yields all names."""
    def_id = uuid4()
    mock_result = MagicMock()
    mock_result.all.return_value = [_row(def_id, "multi-sc", ["orders", "customers"])]
    mock_session_fn.return_value.execute.return_value = mock_result

    out = ScoreDefinition.list_with_table_group_targets("proj")

    assert out == [(def_id, "multi-sc", ["orders", "customers"])]


@patch("testgen.common.models.scores.get_current_session")
def test_list_with_table_group_targets_no_name_filter(mock_session_fn):
    """A scorecard with no table_groups_name filter yields an empty list of targets."""
    def_id = uuid4()
    mock_result = MagicMock()
    # Postgres array_agg with FILTER returns NULL when no rows match — the method
    # must normalize this to [].
    mock_result.all.return_value = [_row(def_id, "metadata-only-sc", None)]
    mock_session_fn.return_value.execute.return_value = mock_result

    out = ScoreDefinition.list_with_table_group_targets("proj")

    assert out == [(def_id, "metadata-only-sc", [])]


@patch("testgen.common.models.scores.get_current_session")
def test_list_with_table_group_targets_filters_by_project_code(mock_session_fn):
    """The query filters on project_code via the WHERE clause."""
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session_fn.return_value.execute.return_value = mock_result

    ScoreDefinition.list_with_table_group_targets("my-project")

    args, _ = mock_session_fn.return_value.execute.call_args
    compiled = args[0].compile(compile_kwargs={"literal_binds": True})
    sql = str(compiled)
    assert "project_code" in sql
    assert "'my-project'" in sql


@patch("testgen.common.models.scores.get_current_session")
def test_list_with_table_group_targets_uses_recursive_cte_on_filter_chain(mock_session_fn):
    """The query SQL walks score_definition_filters via next_filter_id (recursive CTE)."""
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session_fn.return_value.execute.return_value = mock_result

    ScoreDefinition.list_with_table_group_targets("proj")

    args, _ = mock_session_fn.return_value.execute.call_args
    sql = str(args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "RECURSIVE" in sql.upper()
    assert "next_filter_id" in sql
    assert "table_groups_name" in sql


@patch("testgen.common.models.scores.get_current_session")
def test_list_with_table_group_targets_empty_project(mock_session_fn):
    """When the project has no scorecards, returns an empty list."""
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session_fn.return_value.execute.return_value = mock_result

    assert ScoreDefinition.list_with_table_group_targets("proj") == []


@patch("testgen.common.models.scores.get_current_session")
def test_list_with_table_group_targets_dedupes_repeated_names(mock_session_fn):
    """A mode-2 scorecard with N chains all rooted at the same table_groups_name
    must surface that name only once — otherwise the inventory tool lists the
    scorecard once per chain under the same table group."""
    def_id = uuid4()
    mock_result = MagicMock()
    mock_result.all.return_value = [_row(def_id, "redbox-tables", ["redbox"] * 4)]
    mock_session_fn.return_value.execute.return_value = mock_result

    out = ScoreDefinition.list_with_table_group_targets("proj")

    assert out == [(def_id, "redbox-tables", ["redbox"])]


# --- get_overall_issue_ct ---


def _definition_with_filter(project_code="demo", field="business_domain", value="Finance"):
    """Build a transient ScoreDefinition with one filter."""
    definition = ScoreDefinition()
    definition.project_code = project_code
    definition.name = "test"
    definition.total_score = True
    definition.cde_score = False
    definition.criteria = ScoreDefinitionCriteria(
        operand="AND",
        group_by_field=True,
        filters=[ScoreDefinitionFilter(field=field, value=value)],
    )
    return definition


@patch("testgen.common.models.scores.get_current_session")
def test_get_overall_issue_ct_sums_profile_and_test(mock_session_fn):
    """Returns the sum of profile + test issue_ct from the two scoring views."""
    definition = _definition_with_filter()
    # Two execute() calls; first returns profile sum, second returns test sum.
    mock_session_fn.return_value.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=7)),
        MagicMock(scalar=MagicMock(return_value=3)),
    ]

    assert definition.get_overall_issue_ct() == 10


@patch("testgen.common.models.scores.get_current_session")
def test_get_overall_issue_ct_queries_both_views(mock_session_fn):
    """Issues two queries — one against the profile view, one against the test view."""
    definition = _definition_with_filter()
    mock_session_fn.return_value.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=0)),
        MagicMock(scalar=MagicMock(return_value=0)),
    ]

    definition.get_overall_issue_ct()

    calls = mock_session_fn.return_value.execute.call_args_list
    assert len(calls) == 2
    sql_1 = str(calls[0].args[0])
    sql_2 = str(calls[1].args[0])
    assert "v_dq_profile_scoring_latest_by_column" in sql_1
    assert "v_dq_test_scoring_latest_by_column" in sql_2
    # Both queries must use the same filters as as_score_card (project_code + criteria).
    for sql in (sql_1, sql_2):
        assert "project_code = 'demo'" in sql
        assert "business_domain = 'Finance'" in sql


@patch("testgen.common.models.scores.get_current_session")
def test_get_overall_issue_ct_handles_null_scalars(mock_session_fn):
    """A NULL sum (no matching rows) is treated as 0, not None."""
    definition = _definition_with_filter()
    mock_session_fn.return_value.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=None)),
        MagicMock(scalar=MagicMock(return_value=None)),
    ]

    assert definition.get_overall_issue_ct() == 0


@patch("testgen.common.models.scores.get_current_session")
def test_get_overall_issue_ct_no_filters_queries_project_wide(mock_session_fn):
    """With no attribute filters, sum every issue in the project (WHERE project_code only)."""
    definition = ScoreDefinition()
    definition.project_code = "demo"
    definition.name = "test"
    definition.total_score = True
    definition.cde_score = False
    definition.criteria = ScoreDefinitionCriteria(
        operand="AND",
        group_by_field=True,
        filters=[],
    )
    mock_session_fn.return_value.execute.return_value.scalar.side_effect = [4, 7]

    assert definition.get_overall_issue_ct() == 11
    # Two calls: one per scoring view.
    assert mock_session_fn.return_value.execute.call_count == 2
    compiled = mock_session_fn.return_value.execute.call_args_list[0].args[0].compile(
        compile_kwargs={"literal_binds": True}
    )
    assert "project_code = 'demo'" in str(compiled)


# --- list_for_project ---


def _make_scorecard_orm(name: str, project_code: str = "demo") -> ScoreDefinition:
    sd = ScoreDefinition()
    sd.id = uuid4()
    sd.project_code = project_code
    sd.name = name
    sd.total_score = True
    sd.cde_score = False
    return sd


@patch("testgen.common.models.scores.get_current_session")
def test_list_for_project_returns_items_and_total(mock_session_fn):
    """Returns (rows, total) from scalars().unique() and the count scalar."""
    sd_a = _make_scorecard_orm("Apple")
    sd_b = _make_scorecard_orm("Mango")

    session = mock_session_fn.return_value
    session.scalar.return_value = 2
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = [sd_a, sd_b]
    session.scalars.return_value = scalars_result

    items, total = ScoreDefinition.list_for_project("demo", page=1, limit=20)

    assert items == [sd_a, sd_b]
    assert total == 2


@patch("testgen.common.models.scores.get_current_session")
def test_list_for_project_filters_by_project_code(mock_session_fn):
    """The page query's compiled SQL must filter by project_code."""
    session = mock_session_fn.return_value
    session.scalar.return_value = 0
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    session.scalars.return_value = scalars_result

    ScoreDefinition.list_for_project("my-proj")

    page_call = session.scalars.call_args
    sql = str(page_call.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "project_code" in sql
    assert "'my-proj'" in sql


@patch("testgen.common.models.scores.get_current_session")
def test_list_for_project_orders_by_name(mock_session_fn):
    """The page query must include ORDER BY name for stable pagination."""
    session = mock_session_fn.return_value
    session.scalar.return_value = 0
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    session.scalars.return_value = scalars_result

    ScoreDefinition.list_for_project("demo")

    sql = str(session.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "ORDER BY" in sql.upper()
    assert "score_definitions.name" in sql.lower()


@patch("testgen.common.models.scores.get_current_session")
def test_list_for_project_applies_offset_and_limit(mock_session_fn):
    """page=3, limit=10 → OFFSET 20 LIMIT 10."""
    session = mock_session_fn.return_value
    session.scalar.return_value = 100
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    session.scalars.return_value = scalars_result

    ScoreDefinition.list_for_project("demo", page=3, limit=10)

    sql = str(session.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 10" in sql
    assert "OFFSET 20" in sql


@patch("testgen.common.models.scores.get_current_session")
def test_list_for_project_eager_loads_criteria(mock_session_fn):
    """Criteria must be joinedload'd so the rendering loop doesn't fire N+1."""
    session = mock_session_fn.return_value
    session.scalar.return_value = 0
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    session.scalars.return_value = scalars_result

    ScoreDefinition.list_for_project("demo")

    sql = str(session.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    # joinedload emits a LEFT OUTER JOIN against the criteria table.
    assert "score_definition_criteria" in sql.lower()


@patch("testgen.common.models.scores.get_current_session")
def test_list_for_project_count_is_separate_query(mock_session_fn):
    """A scalar count query runs alongside the paged scalars query."""
    session = mock_session_fn.return_value
    session.scalar.return_value = 7
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    session.scalars.return_value = scalars_result

    _, total = ScoreDefinition.list_for_project("demo")

    assert total == 7
    assert session.scalar.call_count == 1
    count_sql = str(session.scalar.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "count(" in count_sql.lower()
    assert "'demo'" in count_sql


@patch("testgen.common.models.scores.get_current_session")
def test_list_for_project_count_null_returns_zero(mock_session_fn):
    """When count() returns NULL on an empty table, normalize to 0."""
    session = mock_session_fn.return_value
    session.scalar.return_value = None
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    session.scalars.return_value = scalars_result

    items, total = ScoreDefinition.list_for_project("demo")
    assert items == []
    assert total == 0


# ─── names_by_id — single batched lookup, no N+1 ──────────────────────


@patch("testgen.common.models.scores.get_current_session")
def test_names_by_id_returns_id_to_name_mapping(mock_session_fn):
    id_a, id_b = uuid4(), uuid4()
    mock_result = MagicMock()
    mock_result.all.return_value = [_row(id_a, "Card A", None), _row(id_b, "Card B", None)]
    mock_session_fn.return_value.execute.return_value = mock_result

    out = ScoreDefinition.names_by_id([id_a, id_b])

    assert out == {id_a: "Card A", id_b: "Card B"}


@patch("testgen.common.models.scores.get_current_session")
def test_names_by_id_empty_input_skips_query(mock_session_fn):
    out = ScoreDefinition.names_by_id([])

    assert out == {}
    mock_session_fn.return_value.execute.assert_not_called()


@patch("testgen.common.models.scores.get_current_session")
def test_names_by_id_uses_single_in_query(mock_session_fn):
    """One IN query for all IDs — not a per-ID lookup (N+1)."""
    ids = [uuid4(), uuid4(), uuid4()]
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session_fn.return_value.execute.return_value = mock_result

    ScoreDefinition.names_by_id(ids)

    assert mock_session_fn.return_value.execute.call_count == 1
    args, _ = mock_session_fn.return_value.execute.call_args
    sql = str(args[0].compile(compile_kwargs={"literal_binds": True}))
    assert " IN (" in sql.upper()
