from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.scores import (
    ScoreCategory,
    ScoreDefinition,
    ScoreDefinitionBreakdownItem,
    ScoreDefinitionCriteria,
)
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions
from testgen.mcp.tools.common import ScoreChainLeafField, ScoreFilterField
from testgen.mcp.tools.quality_scores import _FILTER_SHAPE_DOC, _format_criteria_summary

pytestmark = pytest.mark.unit


# --- Helpers ---


def _score_card(
    score=0.9,
    cde_score=0.8,
    profiling_score=0.95,
    testing_score=0.85,
    categories=None,
):
    """Default ScoreCard dict returned by ScoreDefinition.as_score_card()."""
    return {
        "id": uuid4(),
        "project_code": "demo",
        "name": "test",
        "score": score,
        "cde_score": cde_score,
        "profiling_score": profiling_score,
        "testing_score": testing_score,
        "categories": categories or [],
        "history": [],
        "definition": None,
    }


def _patch_perms(allowed=("demo",), memberships=None):
    """Return a patch context manager that injects a ProjectPermissions with given access."""
    memberships = memberships or dict.fromkeys(allowed, "role_a")
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(
            memberships=memberships, permission="view", username="test_user",
        ),
    )


# --- Argument validation ---


def test_mutually_exclusive_scope_args_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="project_code.*table_group_id"):
        get_quality_scores(project_code="demo", table_group_id=str(uuid4()))


def test_invalid_group_by_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="Invalid group_by") as exc_info:
        get_quality_scores(project_code="demo", group_by="invented_field")
    msg = str(exc_info.value)
    # Error message must speak the user-facing vocabulary.
    assert "Quality Dimension" in msg


@pytest.mark.parametrize("group_by", ["column_name", "table_name", "dq_dimension"])
def test_internal_group_by_value_rejected(group_by, db_session_mock):
    """Old internal column names (row-level or column-form) are no longer accepted."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="Invalid group_by"):
        get_quality_scores(project_code="demo", group_by=group_by)


def test_invalid_score_type_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="Invalid score_type") as exc_info:
        get_quality_scores(project_code="demo", score_type="garbage")
    msg = str(exc_info.value)
    assert "Total" in msg
    assert "CDE" in msg


@pytest.mark.parametrize("internal", ["total", "cde"])
def test_internal_score_type_rejected(internal, db_session_mock):
    """``total``/``cde`` were the old internal codes — inputs now use ``Total``/``CDE``."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="Invalid score_type"):
        get_quality_scores(project_code="demo", score_type=internal)


def test_project_not_accessible_rejected(db_session_mock):
    """A project the user can't view raises MCPResourceNotAccessible-style error."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(allowed=("only_this",)), pytest.raises(MCPResourceNotAccessible, match="forbidden_proj"):
        get_quality_scores(project_code="forbidden_proj")


# --- Score-type → model-call mapping ---


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_default_overall_shows_both_total_and_cde(mock_definition_cls, db_session_mock):
    """score_type omitted → both Total and CDE Score lines are rendered."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.93, cde_score=0.81)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "Total Score" in out
    assert "93" in out
    assert "CDE Score" in out
    assert "81" in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_total_overall_shows_only_total(mock_definition_cls, db_session_mock):
    """score_type='Total' renders only the Total Score line."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.93, cde_score=None)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="Total",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "Total Score" in out
    assert "93" in out
    assert "CDE Score" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_cde_overall_shows_only_cde(mock_definition_cls, db_session_mock):
    """score_type='CDE' renders only the CDE Score line."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=None, cde_score=0.81)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="CDE",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "CDE Score" in out
    assert "81" in out
    assert "Total Score" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_default_overall_includes_profiling_and_testing(mock_definition_cls, db_session_mock):
    """score_type omitted → overall block surfaces Total, CDE, Profiling,
    and Testing — same set the UI's score-card shows when Total is enabled."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(
        score=0.93, cde_score=0.81, profiling_score=0.95, testing_score=0.85,
    )
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "Total Score" in out
    assert "CDE Score" in out
    assert "Profiling Score" in out
    assert "Testing Score" in out
    assert "95" in out
    assert "85" in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_total_overall_includes_profiling_and_testing(mock_definition_cls, db_session_mock):
    """score_type='Total' → Total + Profiling + Testing render; CDE omitted."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(
        score=0.93, cde_score=None, profiling_score=0.95, testing_score=0.85,
    )
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="Total",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "Total Score" in out
    assert "Profiling Score" in out
    assert "Testing Score" in out
    assert "CDE Score" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_cde_overall_omits_profiling_and_testing(mock_definition_cls, db_session_mock):
    """score_type='CDE' → Profiling/Testing must not appear even if the score
    card returns values for them (matches UI's Total-only gating)."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(
        score=None, cde_score=0.81, profiling_score=0.95, testing_score=0.85,
    )
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="CDE",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "CDE Score" in out
    assert "Total Score" not in out
    assert "Profiling Score" not in out
    assert "Testing Score" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_total_grouped_uses_breakdown(mock_definition_cls, db_session_mock):
    """score_type='Total' + group_by sources per-category rows from breakdown.

    Per-category output always includes Impact (matching the Score Explorer UI),
    so the tool reads from get_score_card_breakdown rather than card.categories.
    """
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition.get_score_card_breakdown.return_value = [
        {"business_domain": "Finance", "score": 0.91, "issue_ct": 4, "impact": 3.2},
        {"business_domain": "Marketing", "score": 0.74, "issue_ct": 11, "impact": 9.8},
    ]
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="Total",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "warehouse"}],
            include_impact=True,
        )

    mock_definition.get_score_card_breakdown.assert_called_once_with("score", "business_domain")
    assert "Finance" in out
    assert "Marketing" in out
    assert "Impact on Total Score" in out
    assert "Impact on CDE Score" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_cde_grouped_uses_breakdown(mock_definition_cls, db_session_mock):
    """score_type='CDE' + group_by sources per-category rows from breakdown."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=None, cde_score=0.72)
    mock_definition.get_score_card_breakdown.return_value = [
        {"business_domain": "Finance", "score": 0.80, "issue_ct": 2, "impact": 1.5},
    ]
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="CDE",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "warehouse"}],
            include_impact=True,
        )

    mock_definition.get_score_card_breakdown.assert_called_once_with("cde_score", "business_domain")
    assert "Finance" in out
    assert "Impact on CDE Score" in out
    assert "Impact on Total Score" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_default_grouped_renders_both_score_columns(mock_definition_cls, db_session_mock):
    """score_type omitted + group_by → table has Total + CDE columns and
    Impact columns for both, populated from two breakdown calls.
    """
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9, cde_score=0.7)

    breakdown_results = {
        "score": [
            {"business_domain": "Finance", "score": 0.91, "issue_ct": 4, "impact": 3.2},
            {"business_domain": "Marketing", "score": 0.74, "issue_ct": 12, "impact": 11.4},
        ],
        "cde_score": [
            {"business_domain": "Finance", "score": 0.85, "issue_ct": 3, "impact": 5.0},
            {"business_domain": "Marketing", "score": 0.60, "issue_ct": 8, "impact": 12.0},
        ],
    }
    mock_definition.get_score_card_breakdown.side_effect = (
        lambda score_key, _col: breakdown_results[score_key]
    )
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "warehouse"}],
            include_impact=True,
        )

    # Both score types → two breakdown calls
    assert mock_definition.get_score_card_breakdown.call_count == 2
    call_keys = {c.args[0] for c in mock_definition.get_score_card_breakdown.call_args_list}
    assert call_keys == {"score", "cde_score"}

    assert "Total Score" in out
    assert "CDE Score" in out
    assert "Impact on Total Score" in out
    assert "Impact on CDE Score" in out
    assert "Finance" in out
    assert "Marketing" in out


# --- include_impact ---


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_impact_default_false_omits_impact_columns(mock_definition_cls, db_session_mock):
    """Default include_impact=False → grouped output has no Impact columns."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9, cde_score=0.7)
    breakdown_results = {
        "score": [{"business_domain": "Finance", "score": 0.91, "issue_ct": 4, "impact": 3.2}],
        "cde_score": [{"business_domain": "Finance", "score": 0.85, "issue_ct": 3, "impact": 5.0}],
    }
    mock_definition.get_score_card_breakdown.side_effect = (
        lambda score_key, _col: breakdown_results[score_key]
    )
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    assert "Finance" in out
    assert "Total Score" in out
    assert "CDE Score" in out
    assert "Impact" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_impact_false_total_only_omits_impact_column(mock_definition_cls, db_session_mock):
    """Total-only + default include_impact=False → no impact column."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition.get_score_card_breakdown.return_value = [
        {"business_domain": "Finance", "score": 0.91, "issue_ct": 4, "impact": 3.2},
    ]
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="Total",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    assert "Finance" in out
    assert "Total Score" in out
    assert "Impact" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_impact_false_cde_only_omits_impact_column(mock_definition_cls, db_session_mock):
    """CDE-only + default include_impact=False → no impact column."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=None, cde_score=0.7)
    mock_definition.get_score_card_breakdown.return_value = [
        {"business_domain": "Finance", "score": 0.8, "issue_ct": 3, "impact": 2.0},
    ]
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="CDE",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    assert "Finance" in out
    assert "CDE Score" in out
    assert "Impact" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_impact_false_overall_unaffected(mock_definition_cls, db_session_mock):
    """include_impact only affects grouped output — overall block is unchanged."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.93, cde_score=0.81)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out_default = get_quality_scores(
            project_code="demo",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )
        out_with_impact = get_quality_scores(
            project_code="demo",
            include_impact=True,
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    # No group_by → impact has no rendering surface either way.
    assert "Impact" not in out_default
    assert "Impact" not in out_with_impact


# --- include_issue_ct ---


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_issue_ct_overall_calls_get_overall_issue_ct(mock_definition_cls, db_session_mock):
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition.get_overall_issue_ct.return_value = 42
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            include_issue_ct=True,
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    mock_definition.get_overall_issue_ct.assert_called_once_with()
    assert "Issue Count" in out
    assert "42" in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_issue_ct_grouped_total_uses_simple_label(mock_definition_cls, db_session_mock):
    """grouped + Total + include_issue_ct: single 'Issue Count' column header."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition.get_score_card_breakdown.return_value = [
        {"business_domain": "Finance", "score": 0.91, "issue_ct": 7, "impact": 4.0},
    ]
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="Total",
            group_by="Business Domain",
            include_issue_ct=True,
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    mock_definition.get_score_card_breakdown.assert_called_once_with("score", "business_domain")
    assert "Finance" in out
    assert "7" in out
    assert "Issue Count" in out
    assert "Issue Count (Total)" not in out
    assert "Issue Count (CDE)" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_issue_ct_grouped_cde_uses_simple_label(mock_definition_cls, db_session_mock):
    """grouped + CDE + include_issue_ct: single 'Issue Count' column header."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=None, cde_score=0.7)
    mock_definition.get_score_card_breakdown.return_value = [
        {"business_domain": "Finance", "score": 0.8, "issue_ct": 3, "impact": 2.0},
    ]
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="CDE",
            group_by="Business Domain",
            include_issue_ct=True,
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    mock_definition.get_score_card_breakdown.assert_called_once_with("cde_score", "business_domain")
    assert "Finance" in out
    assert "3" in out
    assert "Issue Count" in out
    assert "Issue Count (Total)" not in out
    assert "Issue Count (CDE)" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_issue_ct_grouped_default_uses_parenthetical_labels(mock_definition_cls, db_session_mock):
    """grouped + score_type unset + include_issue_ct: separate Total / CDE
    issue-count columns, and both Impact columns."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9, cde_score=0.7)
    breakdown_results = {
        "score": [{"business_domain": "Finance", "score": 0.91, "issue_ct": 7, "impact": 4.0}],
        "cde_score": [{"business_domain": "Finance", "score": 0.80, "issue_ct": 3, "impact": 2.0}],
    }
    mock_definition.get_score_card_breakdown.side_effect = (
        lambda score_key, _col: breakdown_results[score_key]
    )
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            group_by="Business Domain",
            include_issue_ct=True,
            include_impact=True,
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    assert mock_definition.get_score_card_breakdown.call_count == 2
    assert "Issue Count (Total)" in out
    assert "Issue Count (CDE)" in out
    assert "Impact on Total Score" in out
    assert "Impact on CDE Score" in out
    # Both per-category issue counts must appear, not just one
    assert "7" in out  # total count
    assert "3" in out  # cde count


# --- Filter semantics passed to the model ---


@patch("testgen.mcp.tools.quality_scores.ScoreDefinitionCriteria")
@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_filters_passed_to_from_filters(mock_definition_cls, mock_criteria_cls, db_session_mock):
    """User filters are handed to ScoreDefinitionCriteria.from_filters."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        get_quality_scores(
            project_code="demo",
            filters=[
                {"field": "Business Domain", "value": "Finance"},
                {"field": "Business Domain", "value": "Marketing"},
                {"field": "Data Source", "value": "warehouse"},
            ],
        )

    # from_filters receives the translated DB column names — the parser
    # converts user-facing labels to internal column names before this call.
    mock_criteria_cls.from_filters.assert_called_once()
    args, kwargs = mock_criteria_cls.from_filters.call_args
    passed = args[0]
    assert {"field": "business_domain", "value": "Finance"} in passed
    assert {"field": "business_domain", "value": "Marketing"} in passed
    assert {"field": "data_source", "value": "warehouse"} in passed
    assert kwargs.get("group_by_field") is True


@patch("testgen.mcp.tools.quality_scores.ScoreDefinitionCriteria")
@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
@patch("testgen.mcp.tools.common.TableGroup")
def test_table_group_adds_implicit_name_filter(
    mock_tg_cls, mock_definition_cls, mock_criteria_cls, db_session_mock,
):
    """When table_group_id is passed, the resolved TG's name is added as a filter."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    tg = MagicMock()
    tg.id = uuid4()
    tg.project_code = "demo"
    tg.table_groups_name = "orders"
    mock_tg_cls.get.return_value = tg

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        get_quality_scores(table_group_id=str(tg.id))

    args, _ = mock_criteria_cls.from_filters.call_args
    passed = args[0]
    assert {"field": "table_groups_name", "value": "orders"} in passed


# --- Cross-project loop ---


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_cross_project_renders_per_project_sections(mock_definition_cls, db_session_mock):
    """No project_code, no table_group_id → one H2 section per accessible project."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition_cls.return_value = mock_definition

    # Pass at least one filter so the tool doesn't fall into the
    # "enumerate every table group in the project" branch (which would need
    # `TableGroup.select_minimal_where` mocked).
    with _patch_perms(allowed=("proj_a", "proj_b")):
        out = get_quality_scores(
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "proj_a" in out
    assert "proj_b" in out
    # `as_score_card` should have been called once per project.
    assert mock_definition.as_score_card.call_count == 2


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_unfiltered_project_uses_project_scoped_definition(mock_definition_cls, db_session_mock):
    """Project-wide call builds a definition with no attribute filters and
    lets the score engine's WHERE ``project_code = ...`` do the scoping."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        get_quality_scores(project_code="demo")

    mock_definition.as_score_card.assert_called_once()
    # Project-wide criteria carries zero attribute filters; the score engine's
    # WHERE ``project_code = ...`` narrows the query.
    assigned_criteria = mock_definition.criteria
    assert list(assigned_criteria.filters) == []


# --- Row cap ---


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_grouped_row_cap_truncates_and_footers(mock_definition_cls, db_session_mock):
    """At >_ROW_CAP category rows, render only top N and surface the cap in a footer."""
    from testgen.mcp.tools.quality_scores import _ROW_CAP, get_quality_scores

    breakdown_rows = [
        {"business_domain": f"L{i}", "score": 0.5 + i * 0.001, "issue_ct": 1, "impact": 0.1}
        for i in range(_ROW_CAP + 10)
    ]
    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition.get_score_card_breakdown.return_value = breakdown_rows
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="Total",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    assert f"Showing top {_ROW_CAP}" in out
    assert str(_ROW_CAP + 10) in out


# --- Empty-breakdown messaging differs based on whether filters were supplied ---


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_grouped_empty_breakdown_with_filters_renders_filter_matched(mock_definition_cls, db_session_mock):
    """User-supplied filter that returns no breakdown rows surfaces 'Filter matched no data.'"""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition.get_score_card_breakdown.return_value = []
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            group_by="Business Domain",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "Filter matched no data" in out
    assert "No category data" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_grouped_empty_breakdown_without_filters_renders_no_category_data(
    mock_definition_cls, db_session_mock,
):
    """Unfiltered project with no breakdown rows keeps the generic 'No category data.' message."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition.get_score_card_breakdown.return_value = []
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            group_by="Business Domain",
        )

    assert "No category data" in out
    assert "Filter matched no data" not in out


# --- Transient definition is never persisted ---


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_transient_definition_never_persisted(mock_definition_cls, db_session_mock):
    """Hardening test: the MCP tool never calls .save() on its transient definition."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        get_quality_scores(
            project_code="demo",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    mock_definition.save.assert_not_called()


# ============================================================
# Scorecard tools — merged in from test_tools_scorecards.py
# ============================================================

def _criteria(filters: list[dict], group_by_field: bool = True) -> ScoreDefinitionCriteria:
    return ScoreDefinitionCriteria.from_filters(filters, group_by_field=group_by_field)




def _fake_definition(
    name: str,
    *,
    project_code: str = "demo",
    total: bool = True,
    cde: bool = False,
    category: ScoreCategory | None = None,
    filters: list[dict] | None = None,
    group_by_field: bool = True,
    score: float | None = 0.95,
    cde_value: float | None = 0.90,
) -> ScoreDefinition:
    sd = ScoreDefinition()
    sd.id = uuid4()
    sd.project_code = project_code
    sd.name = name
    sd.total_score = total
    sd.cde_score = cde
    sd.category = category
    sd.criteria = ScoreDefinitionCriteria.from_filters(
        filters or [{"field": "table_groups_name", "value": "tg1"}],
        group_by_field=group_by_field,
    )
    sd._fake_card = {"score": score, "cde_score": cde_value}
    return sd


@pytest.fixture
def patch_card(monkeypatch):
    """Route as_cached_score_card to the stub stored on each fake definition."""
    def _cached(self, include_definition: bool = False):
        return self._fake_card
    monkeypatch.setattr(ScoreDefinition, "as_cached_score_card", _cached)


def _patch_list(items, total):
    return patch.object(ScoreDefinition, "list_for_project", return_value=(items, total))


# --- _format_criteria_summary ---


def test_format_criteria_summary_none():
    assert _format_criteria_summary(None) == "(no filters)"


def test_format_criteria_summary_empty():
    criteria = ScoreDefinitionCriteria(operand="AND", filters=[], group_by_field=True)
    assert _format_criteria_summary(criteria) == "(no filters)"


def test_format_criteria_summary_single_filter_uses_display_label():
    criteria = _criteria([{"field": "table_groups_name", "value": "sales"}])
    assert _format_criteria_summary(criteria) == "Table Group = sales"


def test_format_criteria_summary_or_within_field():
    """group_by_field=True with multiple roots on the same field renders as `in (...)`."""
    criteria = _criteria([
        {"field": "table_groups_name", "value": "sales"},
        {"field": "table_groups_name", "value": "marketing"},
    ])
    assert _format_criteria_summary(criteria) == "Table Group in (sales, marketing)"


def test_format_criteria_summary_and_across_fields():
    criteria = _criteria([
        {"field": "table_groups_name", "value": "sales"},
        {"field": "business_domain", "value": "Finance"},
    ])
    # Ordering is alphabetical by display label for stable output.
    assert _format_criteria_summary(criteria) == "Business Domain = Finance AND Table Group = sales"


def test_format_criteria_summary_chained_next_filter():
    """A root filter with `others` becomes a next_filter AND-chain inside the root."""
    criteria = ScoreDefinitionCriteria.from_filters(
        [{
            "field": "table_groups_name",
            "value": "sales",
            "others": [{"field": "business_domain", "value": "Finance"}],
        }],
        group_by_field=True,
    )
    summary = _format_criteria_summary(criteria)
    assert "Table Group = sales" in summary
    assert "Business Domain = Finance" in summary
    assert " AND " in summary


def test_format_criteria_summary_unknown_field_falls_back_to_raw_column():
    criteria = _criteria([{"field": "made_up_column", "value": "x"}])
    assert _format_criteria_summary(criteria) == "made_up_column = x"


def test_format_criteria_summary_mode_2_chained_uses_table_label():
    """A chain into table_name renders the user-facing "Table" label, not the column name."""
    criteria = ScoreDefinitionCriteria.from_filters(
        [{
            "field": "table_groups_name",
            "value": "redbox",
            "others": [{"field": "table_name", "value": "accounts"}],
        }],
        group_by_field=False,
    )
    summary = _format_criteria_summary(criteria)
    assert "Table Group = redbox" in summary
    assert "Table = accounts" in summary
    assert "table_name" not in summary


def test_format_criteria_summary_mode_2_chained_uses_column_label():
    criteria = ScoreDefinitionCriteria.from_filters(
        [{
            "field": "table_groups_name",
            "value": "redbox",
            "others": [
                {"field": "table_name", "value": "accounts"},
                {"field": "column_name", "value": "id"},
            ],
        }],
        group_by_field=False,
    )
    summary = _format_criteria_summary(criteria)
    assert "Column = id" in summary
    assert "column_name" not in summary


def test_format_criteria_summary_mode_2_sibling_chains_collapse_to_in():
    """Chains sharing the same root (table_groups_name=X) collapse to `Table in (...)`."""
    criteria = ScoreDefinitionCriteria.from_filters(
        [
            {"field": "table_groups_name", "value": "redbox",
             "others": [{"field": "table_name", "value": "a"}]},
            {"field": "table_groups_name", "value": "redbox",
             "others": [{"field": "table_name", "value": "b"}]},
            {"field": "table_groups_name", "value": "redbox",
             "others": [{"field": "table_name", "value": "c"}]},
        ],
        group_by_field=False,
    )
    summary = _format_criteria_summary(criteria)
    assert summary == "Table Group = redbox AND Table in (a, b, c)"


def test_format_criteria_summary_mode_2_different_roots_or_joined():
    """Chains with different table_groups_name roots are OR-joined (not AND-joined)."""
    criteria = ScoreDefinitionCriteria.from_filters(
        [
            {"field": "table_groups_name", "value": "redbox",
             "others": [{"field": "table_name", "value": "a"}]},
            {"field": "table_groups_name", "value": "sales",
             "others": [{"field": "table_name", "value": "b"}]},
        ],
        group_by_field=False,
    )
    summary = _format_criteria_summary(criteria)
    assert " OR " in summary
    assert " AND " not in summary.replace(" AND Table = ", "")  # AND only inside a chain
    assert "redbox" in summary
    assert "sales" in summary


# --- list_scorecards tool ---


def test_list_scorecards_requires_view_access(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import list_scorecards

    with _patch_perms(allowed=("only_this",)), pytest.raises(
        MCPResourceNotAccessible, match="forbidden_proj"
    ):
        list_scorecards("forbidden_proj")


def test_list_scorecards_empty_renders_friendly_message(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import list_scorecards

    with _patch_perms(), _patch_list([], 0):
        out = list_scorecards("demo")
    assert "Scorecards in Project `demo`" in out
    assert "_No scorecards configured._" in out


def test_list_scorecards_renders_total_and_cde(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import list_scorecards

    items = [
        _fake_definition(
            "Sales Quality",
            total=True,
            cde=True,
            category=ScoreCategory.dq_dimension,
            filters=[{"field": "table_groups_name", "value": "sales"}],
            score=0.95,
            cde_value=0.90,
        ),
    ]
    with _patch_perms(), _patch_list(items, 1):
        out = list_scorecards("demo")
    assert "Sales Quality" in out
    assert "Total Score" in out
    assert "CDE Score" in out
    assert "Quality Dimension" in out  # display label for dq_dimension
    assert "Table Group = sales" in out
    assert "0.95" in out or "95" in out
    assert "0.90" in out or "90" in out


def test_list_scorecards_hides_cde_when_disabled(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import list_scorecards

    items = [_fake_definition("Only Total", total=True, cde=False, cde_value=None)]
    with _patch_perms(), _patch_list(items, 1):
        out = list_scorecards("demo")
    assert "Total Score" in out
    assert "CDE Score" not in out


def test_list_scorecards_hides_total_when_disabled(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import list_scorecards

    items = [_fake_definition("CDE Only", total=False, cde=True, score=None, cde_value=0.50)]
    with _patch_perms(), _patch_list(items, 1):
        out = list_scorecards("demo")
    assert "CDE Score" in out
    assert "Total Score" not in out


def test_list_scorecards_includes_profiling_and_testing_when_total_enabled(db_session_mock, patch_card):
    """When total_score is enabled, the per-scorecard block surfaces Profiling
    Score and Testing Score — matching the UI's score-card and get_scorecard."""
    from testgen.mcp.tools.quality_scores import list_scorecards

    sd = _fake_definition(
        "Full Card",
        total=True,
        cde=True,
        score=0.925,
        cde_value=0.880,
    )
    sd._fake_card.update({"profiling_score": 0.950, "testing_score": 0.900})
    with _patch_perms(), _patch_list([sd], 1):
        out = list_scorecards("demo")
    assert "Profiling Score" in out
    assert "Testing Score" in out
    # friendly_score scales by 100 and rounds to 1 decimal.
    assert "95" in out
    assert "90" in out


def test_list_scorecards_omits_profiling_and_testing_for_cde_only_scorecard(db_session_mock, patch_card):
    """When total_score is disabled, Profiling/Testing must not appear even
    though as_cached_score_card may return values for them."""
    from testgen.mcp.tools.quality_scores import list_scorecards

    sd = _fake_definition("CDE Only", total=False, cde=True, score=None, cde_value=0.50)
    sd._fake_card.update({"profiling_score": 0.7, "testing_score": 0.8})
    with _patch_perms(), _patch_list([sd], 1):
        out = list_scorecards("demo")
    assert "CDE Score" in out
    assert "Profiling Score" not in out
    assert "Testing Score" not in out


def test_list_scorecards_omits_breakdown_when_no_category(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import list_scorecards

    items = [_fake_definition("Plain", category=None)]
    with _patch_perms(), _patch_list(items, 1):
        out = list_scorecards("demo")
    assert "Category" not in out


def test_list_scorecards_emits_pagination_info_and_footer(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import list_scorecards

    items = [_fake_definition(f"Card {i}") for i in range(3)]
    with _patch_perms(), _patch_list(items, 25):
        out = list_scorecards("demo", page=1, limit=3)
    # format_page_info emits an en-dash (\u2013) between start and end.
    assert "Showing 1\u20133 of 25" in out
    assert "Use `page=2` for more" in out


def test_list_scorecards_empty_page_past_end(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import list_scorecards

    with _patch_perms(), _patch_list([], 3):
        out = list_scorecards("demo", page=5, limit=10)
    # No-scorecards-on-page message references current page + total
    assert "page 5" in out
    assert "total: 3" in out


@pytest.mark.parametrize("page,limit", [(0, 10), (1, 0), (1, 101)])
def test_list_scorecards_rejects_invalid_pagination(db_session_mock, patch_card, page, limit):
    from testgen.mcp.tools.quality_scores import list_scorecards

    with _patch_perms(), pytest.raises(MCPUserError):
        list_scorecards("demo", page=page, limit=limit)


def test_list_scorecards_renders_filter_chain(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import list_scorecards

    items = [_fake_definition(
        "Multi-filter",
        filters=[
            {"field": "table_groups_name", "value": "sales"},
            {"field": "business_domain", "value": "Finance"},
        ],
    )]
    with _patch_perms(), _patch_list(items, 1):
        out = list_scorecards("demo")
    assert "Business Domain = Finance" in out
    assert "Table Group = sales" in out
    assert " AND " in out


# --- get_scorecard tool ---


def _fake_breakdown_item(
    *,
    category: str,
    score_type: str,
    field_values: dict,
    impact: float = 0.5,
    score: float = 0.85,
    issue_ct: int = 3,
):
    """Build a fake `ScoreDefinitionBreakdownItem`-like object exposing ``.to_dict()``.

    Matches the shape produced by the real ``to_dict`` — category-specific fields
    plus ``impact``, ``score``, ``issue_ct``.
    """
    item = MagicMock(spec=ScoreDefinitionBreakdownItem)
    item.category = category
    item.score_type = score_type
    item.to_dict = MagicMock(return_value={
        **field_values,
        "impact": impact,
        "score": score,
        "issue_ct": issue_ct,
    })
    return item


def _patch_get(definition):
    return patch.object(ScoreDefinition, "get", return_value=definition)


def _patch_breakdown(items):
    return patch.object(ScoreDefinitionBreakdownItem, "filter", return_value=items)


def _patch_breakdown_by_score_type(total, cde):
    """Return different breakdown rows depending on the requested ``score_type``."""
    def _filter(*, definition_id, category, score_type):
        return total if score_type == "score" else cde
    return patch.object(ScoreDefinitionBreakdownItem, "filter", side_effect=_filter)


def test_get_scorecard_rejects_invalid_uuid(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    with _patch_perms(), pytest.raises(MCPUserError, match="not a valid UUID"):
        get_scorecard("not-a-uuid")


def test_get_scorecard_unknown_id_returns_not_accessible(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    missing_id = str(uuid4())
    with _patch_perms(), _patch_get(None), pytest.raises(
        MCPResourceNotAccessible, match=missing_id
    ):
        get_scorecard(missing_id)


def test_get_scorecard_forbidden_project_returns_not_accessible(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    sd = _fake_definition("Other-project card", project_code="forbidden_proj")
    with _patch_perms(allowed=("demo",)), _patch_get(sd), pytest.raises(
        MCPResourceNotAccessible, match=str(sd.id)
    ):
        get_scorecard(str(sd.id))


def test_get_scorecard_renders_overall_scores(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    sd = _fake_definition(
        "Sales Quality",
        total=True,
        cde=True,
        category=ScoreCategory.dq_dimension,
        score=0.95,
        cde_value=0.90,
    )
    sd._fake_card.update({"profiling_score": 0.88, "testing_score": 0.91})
    with _patch_perms(), _patch_get(sd), _patch_breakdown([]):
        out = get_scorecard(str(sd.id))
    assert "Sales Quality" in out
    assert "Total Score" in out
    assert "CDE Score" in out
    assert "Profiling Score" in out
    assert "Testing Score" in out
    # Filter summary is preserved from list_scorecards behavior.
    assert "Table Group = tg1" in out


def test_get_scorecard_hides_total_when_disabled(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    sd = _fake_definition(
        "CDE-Only Card",
        total=False,
        cde=True,
        category=None,
        score=None,
        cde_value=0.5,
    )
    with _patch_perms(), _patch_get(sd), _patch_breakdown([]):
        out = get_scorecard(str(sd.id))
    assert "CDE Score" in out
    assert "Total Score" not in out
    # Profiling/Testing are components of the Total score — should be hidden too.
    assert "Profiling Score" not in out
    assert "Testing Score" not in out


def test_get_scorecard_hides_cde_when_disabled(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    sd = _fake_definition(
        "Total-Only Card",
        total=True,
        cde=False,
        category=None,
        cde_value=None,
    )
    sd._fake_card.update({"profiling_score": 0.7, "testing_score": 0.8})
    with _patch_perms(), _patch_get(sd), _patch_breakdown([]):
        out = get_scorecard(str(sd.id))
    assert "Total Score" in out
    assert "Profiling Score" in out
    assert "Testing Score" in out
    assert "CDE Score" not in out


def test_get_scorecard_omits_breakdown_when_no_category(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    sd = _fake_definition("Plain", category=None)
    sd._fake_card.update({"profiling_score": 0.7, "testing_score": 0.8})
    with _patch_perms(), _patch_get(sd), _patch_breakdown([]):
        out = get_scorecard(str(sd.id))
    assert "Category" not in out


def test_get_scorecard_renders_breakdown_wide_table(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    sd = _fake_definition(
        "Wide breakdown",
        total=True,
        cde=True,
        category=ScoreCategory.dq_dimension,
    )
    sd._fake_card.update({"profiling_score": 0.7, "testing_score": 0.8})

    total_items = [
        _fake_breakdown_item(
            category="dq_dimension",
            score_type="score",
            field_values={"dq_dimension": "Accuracy"},
            impact=0.4,
            score=0.6,
            issue_ct=10,
        ),
    ]
    cde_items = [
        _fake_breakdown_item(
            category="dq_dimension",
            score_type="cde_score",
            field_values={"dq_dimension": "Accuracy"},
            impact=0.3,
            score=0.7,
            issue_ct=5,
        ),
    ]

    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_breakdown_by_score_type(total_items, cde_items),
    ):
        out = get_scorecard(str(sd.id))
    assert "Breakdown by Quality Dimension" in out
    assert "Accuracy" in out
    # Both score types in headers — parenthetical disambiguates which column is which.
    assert "Issue Count (Total)" in out
    assert "Issue Count (CDE)" in out
    assert "Impact on Total Score" in out
    assert "Impact on CDE Score" in out


def test_get_scorecard_breakdown_single_score_type(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    sd = _fake_definition(
        "Single-type breakdown",
        total=True,
        cde=False,
        category=ScoreCategory.business_domain,
        cde_value=None,
    )
    sd._fake_card.update({"profiling_score": 0.7, "testing_score": 0.8})

    items = [
        _fake_breakdown_item(
            category="business_domain",
            score_type="score",
            field_values={"business_domain": "Finance"},
        ),
    ]
    with _patch_perms(), _patch_get(sd), _patch_breakdown(items):
        out = get_scorecard(str(sd.id))
    assert "Breakdown by Business Domain" in out
    assert "Finance" in out
    # When only one type is enabled, headers drop the parenthetical (mirrors get_quality_scores).
    assert "Issue Count (Total)" not in out
    assert "Issue Count (CDE)" not in out


def test_get_scorecard_breakdown_caps_at_100(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    sd = _fake_definition(
        "Many rows",
        total=True,
        cde=False,
        category=ScoreCategory.business_domain,
        cde_value=None,
    )
    sd._fake_card.update({"profiling_score": 0.7, "testing_score": 0.8})

    items = [
        _fake_breakdown_item(
            category="business_domain",
            score_type="score",
            field_values={"business_domain": f"Domain {i}"},
            impact=0.5 - 0.001 * i,
        )
        for i in range(101)
    ]
    with _patch_perms(), _patch_get(sd), _patch_breakdown(items):
        out = get_scorecard(str(sd.id))
    assert "Showing top 100 of 101" in out


def test_get_scorecard_breakdown_empty(db_session_mock, patch_card):
    from testgen.mcp.tools.quality_scores import get_scorecard

    sd = _fake_definition(
        "No data",
        total=True,
        cde=False,
        category=ScoreCategory.dq_dimension,
        cde_value=None,
    )
    sd._fake_card.update({"profiling_score": 0.7, "testing_score": 0.8})
    with _patch_perms(), _patch_get(sd), _patch_breakdown([]):
        out = get_scorecard(str(sd.id))
    assert "Breakdown by Quality Dimension" in out
    assert "_No breakdown data._" in out


# --- delete_scorecard tool ---


def test_delete_scorecard_rejects_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.quality_scores import delete_scorecard

    with _patch_perms(), pytest.raises(MCPUserError, match="not a valid UUID"):
        delete_scorecard("not-a-uuid")


def test_delete_scorecard_unknown_id_returns_not_accessible(db_session_mock):
    from testgen.mcp.tools.quality_scores import delete_scorecard

    missing_id = str(uuid4())
    with _patch_perms(), _patch_get(None), pytest.raises(
        MCPResourceNotAccessible, match=missing_id
    ):
        delete_scorecard(missing_id)


def test_delete_scorecard_forbidden_project_does_not_call_delete(db_session_mock):
    from testgen.mcp.tools.quality_scores import delete_scorecard

    sd = _fake_definition("Other-project card", project_code="forbidden_proj")
    with (
        _patch_perms(allowed=("demo",)),
        _patch_get(sd),
        patch.object(ScoreDefinition, "delete") as mock_delete,
        pytest.raises(MCPResourceNotAccessible, match=str(sd.id)),
    ):
        delete_scorecard(str(sd.id))
    assert mock_delete.called is False


def test_delete_scorecard_calls_model_delete(db_session_mock):
    from testgen.mcp.tools.quality_scores import delete_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        patch.object(ScoreDefinition, "delete") as mock_delete,
    ):
        delete_scorecard(str(sd.id))
    mock_delete.assert_called_once()


def test_delete_scorecard_returns_confirmation_with_name_id_project(db_session_mock):
    from testgen.mcp.tools.quality_scores import delete_scorecard

    sd = _fake_definition("Sales Quality", project_code="demo")
    with _patch_perms(), _patch_get(sd), patch.object(ScoreDefinition, "delete"):
        out = delete_scorecard(str(sd.id))
    assert "Sales Quality" in out
    assert str(sd.id) in out
    assert "demo" in out


# --- update_scorecard tool ---


def _patch_orchestrator():
    """Stub the persist+refresh orchestrator so unit tests don't hit the DB."""
    return patch("testgen.mcp.tools.quality_scores.save_and_refresh_score_definition")


def test_update_scorecard_rejects_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    with _patch_perms(), pytest.raises(MCPUserError, match="not a valid UUID"):
        update_scorecard("not-a-uuid", name="x")


def test_update_scorecard_unknown_id_returns_not_accessible(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    missing_id = str(uuid4())
    with _patch_perms(), _patch_get(None), pytest.raises(
        MCPResourceNotAccessible, match=missing_id
    ):
        update_scorecard(missing_id, name="x")


def test_update_scorecard_forbidden_project_does_not_call_save(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Other-project card", project_code="forbidden_proj")
    with (
        _patch_perms(allowed=("demo",)),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPResourceNotAccessible, match=str(sd.id)),
    ):
        update_scorecard(str(sd.id), name="x")
    mock_orch.assert_not_called()


def test_update_scorecard_no_fields_supplied_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="No fields supplied"),
    ):
        update_scorecard(str(sd.id))
    mock_orch.assert_not_called()


def test_update_scorecard_empty_name_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="name"),
    ):
        update_scorecard(str(sd.id), name="")
    mock_orch.assert_not_called()
    assert sd.name == "Sales Quality"


def test_update_scorecard_unknown_category_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="category"),
    ):
        update_scorecard(str(sd.id), category="not_a_category")
    mock_orch.assert_not_called()


def test_update_scorecard_filter_without_field_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="field"),
    ):
        update_scorecard(str(sd.id), filters=[{"value": "x"}])
    mock_orch.assert_not_called()


def test_update_scorecard_empty_filters_list_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="filter"),
    ):
        update_scorecard(str(sd.id), filters=[])
    mock_orch.assert_not_called()


def test_update_scorecard_changes_name(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with _patch_perms(), _patch_get(sd), _patch_orchestrator() as mock_orch:
        update_scorecard(str(sd.id), name="Renamed Card")
    assert sd.name == "Renamed Card"
    mock_orch.assert_called_once()


def test_update_scorecard_toggles_show_total_score(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality", total=True)
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        update_scorecard(str(sd.id), show_total_score=False)
    assert sd.total_score is False


def test_update_scorecard_toggles_show_cde_score(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality", cde=False)
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        update_scorecard(str(sd.id), show_cde_score=True)
    assert sd.cde_score is True


def test_update_scorecard_sets_category(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality", category=None)
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        update_scorecard(str(sd.id), category="Quality Dimension")
    assert sd.category == ScoreCategory.dq_dimension


def test_update_scorecard_clears_category(db_session_mock):
    """Passing an empty ``category`` clears it — distinct from ``None`` (no change)."""
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality", category=ScoreCategory.dq_dimension)
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        update_scorecard(str(sd.id), category="")
    assert sd.category is None


def test_update_scorecard_replaces_filters(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition(
        "Sales Quality",
        filters=[{"field": "table_groups_name", "value": "tg1"}],
    )
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        update_scorecard(
            str(sd.id),
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )
    new_filters = list(sd.criteria)
    assert len(new_filters) == 1
    assert new_filters[0]["field"] == "business_domain"
    assert new_filters[0]["value"] == "Finance"


def test_update_scorecard_flat_filters_derive_group_by_field_true(db_session_mock):
    """Mode 1 shape (flat category filters) → group_by_field=True, regardless of prior state."""
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition(
        "Sales Quality",
        filters=[{
            "field": "table_groups_name",
            "value": "sales",
            "others": [{"field": "table_name", "value": "orders"}],
        }],
        group_by_field=False,
    )
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        update_scorecard(
            str(sd.id),
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )
    assert sd.criteria.group_by_field is True


def test_update_scorecard_chained_filters_derive_group_by_field_false(db_session_mock):
    """Mode 2 shape (any chained filter) → group_by_field=False, regardless of prior state."""
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition(
        "Sales Quality",
        filters=[{"field": "table_groups_name", "value": "tg1"}],
        group_by_field=True,
    )
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        update_scorecard(
            str(sd.id),
            filters=[
                {
                    "field": "Table Group",
                    "value": "sales",
                    "others": [{"field": "Table", "value": "orders"}],
                },
                {
                    "field": "Table Group",
                    "value": "sales",
                    "others": [{"field": "Table", "value": "customers"}],
                },
            ],
        )
    assert sd.criteria.group_by_field is False


def test_update_scorecard_mode_1_filter_with_non_category_field_rejected(db_session_mock):
    """Flat filter using "Table" (chain-leaf field) must be rejected at the flat level."""
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="Table"),
    ):
        update_scorecard(
            str(sd.id),
            filters=[{"field": "Table", "value": "orders"}],
        )
    mock_orch.assert_not_called()


def test_update_scorecard_mode_2_chain_must_root_at_table_group(db_session_mock):
    """Chained filters must start at "Table Group" (matches UI column-selector shape)."""
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="Table Group"),
    ):
        update_scorecard(
            str(sd.id),
            filters=[{
                "field": "Data Source",
                "value": "S",
                "others": [{"field": "Table", "value": "x"}],
            }],
        )
    mock_orch.assert_not_called()


def test_update_scorecard_mode_2_chain_must_chain_into_table_or_column(db_session_mock):
    """Chain leaves must be "Table" or "Column" — not category fields."""
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="Business Domain"),
    ):
        update_scorecard(
            str(sd.id),
            filters=[{
                "field": "Table Group",
                "value": "sales",
                "others": [{"field": "Business Domain", "value": "Finance"}],
            }],
        )
    mock_orch.assert_not_called()


def test_update_scorecard_mode_2_chain_table_then_column_accepted(db_session_mock):
    """A full chain "Table Group" → "Table" → "Column" is valid."""
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        update_scorecard(
            str(sd.id),
            filters=[{
                "field": "Table Group",
                "value": "sales",
                "others": [
                    {"field": "Table", "value": "orders"},
                    {"field": "Column", "value": "id"},
                ],
            }],
        )
    assert sd.criteria.group_by_field is False
    roots = list(sd.criteria)
    assert roots[0]["others"][0]["field"] == "table_name"
    assert roots[0]["others"][1]["field"] == "column_name"


def test_update_scorecard_diff_uses_display_labels(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality", total=True, category=None)
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        out = update_scorecard(
            str(sd.id),
            show_total_score=False,
            category="Quality Dimension",
        )
    assert "Total Score" in out
    assert "Category" in out
    assert "Quality Dimension" in out
    # Internal names must not leak.
    assert "total_score" not in out
    assert "dq_dimension" not in out


def test_update_scorecard_diff_omits_unchanged_fields(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality", total=True, cde=False, category=None)
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        out = update_scorecard(str(sd.id), name="Renamed")
    assert "Name" in out
    assert "Total Score" not in out
    assert "CDE Score" not in out
    assert "Category" not in out
    assert "Filters" not in out


def test_update_scorecard_response_includes_id_and_project(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality", project_code="demo")
    with _patch_perms(), _patch_get(sd), _patch_orchestrator():
        out = update_scorecard(str(sd.id), name="Renamed")
    assert str(sd.id) in out
    assert "demo" in out


def test_update_scorecard_calls_save_and_refresh_with_is_new_false(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with _patch_perms(), _patch_get(sd), _patch_orchestrator() as mock_orch:
        update_scorecard(str(sd.id), name="Renamed")
    mock_orch.assert_called_once()
    args, kwargs = mock_orch.call_args
    assert args[0] is sd
    assert kwargs == {"is_new": False}


def test_update_scorecard_does_not_call_orchestrator_on_filter_validation_failure(db_session_mock):
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="field"),
    ):
        update_scorecard(
            str(sd.id),
            name="Renamed",
            filters=[{"value": "x"}],
        )
    mock_orch.assert_not_called()
    # Name must not be mutated when a later validation step rejects the payload.
    assert sd.name == "Sales Quality"


# --- create_scorecard ---


_VALID_FILTER = [{"field": "Table Group", "value": "tg1"}]


def test_create_scorecard_unknown_project_returns_not_accessible(db_session_mock):
    from testgen.mcp.tools.quality_scores import create_scorecard

    with (
        _patch_perms(allowed=("demo",)),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPResourceNotAccessible, match="forbidden_proj"),
    ):
        create_scorecard("forbidden_proj", "My Card", filters=_VALID_FILTER)
    mock_orch.assert_not_called()


def test_create_scorecard_rejects_blank_name(db_session_mock):
    from testgen.mcp.tools.quality_scores import create_scorecard

    with (
        _patch_perms(),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="name"),
    ):
        create_scorecard("demo", "   ", filters=_VALID_FILTER)
    mock_orch.assert_not_called()


def test_create_scorecard_requires_filters(db_session_mock):
    from testgen.mcp.tools.quality_scores import create_scorecard

    with (
        _patch_perms(),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="filter"),
    ):
        create_scorecard("demo", "My Card", filters=[])
    mock_orch.assert_not_called()


def test_create_scorecard_rejects_invalid_filter_field(db_session_mock):
    """dq_dimension is a group_by field, not a flat scorecard filter field."""
    from testgen.mcp.tools.quality_scores import create_scorecard

    with (
        _patch_perms(),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="dq_dimension"),
    ):
        create_scorecard(
            "demo",
            "My Card",
            filters=[{"field": "dq_dimension", "value": "Validity"}],
        )
    mock_orch.assert_not_called()


def test_create_scorecard_rejects_filter_value_with_forbidden_chars(db_session_mock):
    """Persisted scorecard filters must reject SQL-injection chars — values flow
    into raw SQL via ``ScoreDefinitionCriteria.get_as_sql``."""
    from testgen.mcp.tools.quality_scores import create_scorecard

    with (
        _patch_perms(),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="forbidden"),
    ):
        create_scorecard(
            "demo",
            "My Card",
            filters=[{"field": "Table Group", "value": "tg1' OR '1'='1"}],
        )
    mock_orch.assert_not_called()


def test_create_scorecard_rejects_filter_value_too_long(db_session_mock):
    """Persisted scorecard filter values must respect ``_VALUE_MAX_LEN``."""
    from testgen.mcp.tools.quality_scores import create_scorecard

    with (
        _patch_perms(),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="too long"),
    ):
        create_scorecard(
            "demo",
            "My Card",
            filters=[{"field": "Table Group", "value": "x" * 300}],
        )
    mock_orch.assert_not_called()


def test_create_scorecard_rejects_chain_leaf_value_with_forbidden_chars(db_session_mock):
    """Chain-leaf values (``others[].value``) also flow into raw SQL — same check."""
    from testgen.mcp.tools.quality_scores import create_scorecard

    with (
        _patch_perms(),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="forbidden"),
    ):
        create_scorecard(
            "demo",
            "My Card",
            filters=[{
                "field": "Table Group",
                "value": "tg1",
                "others": [{"field": "Table", "value": "t'; DROP TABLE--"}],
            }],
        )
    mock_orch.assert_not_called()


def test_update_scorecard_rejects_filter_value_with_forbidden_chars(db_session_mock):
    """Update path mirrors create — persisted filter values must be safe."""
    from testgen.mcp.tools.quality_scores import update_scorecard

    sd = _fake_definition("Sales Quality")
    with (
        _patch_perms(),
        _patch_get(sd),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="forbidden"),
    ):
        update_scorecard(
            str(sd.id),
            filters=[{"field": "Table Group", "value": 'tg1"'}],
        )
    mock_orch.assert_not_called()


def test_create_scorecard_rejects_invalid_category(db_session_mock):
    from testgen.mcp.tools.quality_scores import create_scorecard

    with (
        _patch_perms(),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError, match="Invalid category"),
    ):
        create_scorecard(
            "demo",
            "My Card",
            filters=_VALID_FILTER,
            category="Not A Category",
        )
    mock_orch.assert_not_called()


def test_create_scorecard_persists_with_defaults(db_session_mock):
    from testgen.mcp.tools.quality_scores import create_scorecard

    with _patch_perms(), _patch_orchestrator() as mock_orch:
        create_scorecard("demo", "My Card", filters=_VALID_FILTER)

    assert mock_orch.call_count == 1
    saved = mock_orch.call_args.args[0]
    assert isinstance(saved, ScoreDefinition)
    assert saved.project_code == "demo"
    assert saved.name == "My Card"
    assert saved.total_score is True
    assert saved.cde_score is False
    assert saved.category is None
    assert saved.criteria.group_by_field is True
    assert saved.criteria.filters[0].field == "table_groups_name"
    assert saved.criteria.filters[0].value == "tg1"
    assert mock_orch.call_args.kwargs == {"is_new": True}


def test_create_scorecard_persists_with_overrides(db_session_mock):
    from testgen.mcp.tools.quality_scores import create_scorecard

    with _patch_perms(), _patch_orchestrator() as mock_orch:
        create_scorecard(
            "demo",
            "My Card",
            filters=_VALID_FILTER,
            category="Quality Dimension",
            show_total_score=False,
            show_cde_score=True,
        )

    saved = mock_orch.call_args.args[0]
    assert saved.total_score is False
    assert saved.cde_score is True
    assert saved.category == ScoreCategory.dq_dimension


def test_create_scorecard_persists_mode_2_chained_filters(db_session_mock):
    from testgen.mcp.tools.quality_scores import create_scorecard

    chained = [{
        "field": "Table Group",
        "value": "tg1",
        "others": [
            {"field": "Table", "value": "accounts"},
            {"field": "Column", "value": "id"},
        ],
    }]
    with _patch_perms(), _patch_orchestrator() as mock_orch:
        create_scorecard("demo", "My Card", filters=chained)

    saved = mock_orch.call_args.args[0]
    assert saved.criteria.group_by_field is False
    root = saved.criteria.filters[0]
    assert root.field == "table_groups_name"
    assert root.value == "tg1"
    assert root.next_filter is not None
    assert root.next_filter.field == "table_name"
    assert root.next_filter.next_filter.field == "column_name"


def test_create_scorecard_returns_markdown_summary(db_session_mock):
    from testgen.mcp.tools.quality_scores import create_scorecard

    new_id = uuid4()

    def _set_id(definition, *, is_new):
        definition.id = new_id
        return definition

    with _patch_perms(), _patch_orchestrator() as mock_orch:
        mock_orch.side_effect = _set_id
        out = create_scorecard(
            "demo",
            "Finance Card",
            filters=_VALID_FILTER,
            category="Quality Dimension",
        )

    assert "Finance Card" in out
    assert "demo" in out
    assert str(new_id) in out
    # Display label uses "Category", not "Breakdown By".
    assert "Category" in out
    assert "Breakdown By" not in out
    # Friendly category label, not internal column name.
    assert "Quality Dimension" in out
    assert "dq_dimension" not in out
    # Filter summary appears.
    assert "Filters" in out


# ============================================================
# Exhaustive corner-case coverage for the unified _validate_filters
# Each numbered test maps 1-to-1 to a case in the plan's Task 2 enumeration.
# Calls into _validate_filters directly (no MCP wrapper) except
# where the contract requires going through the tool itself.
# ============================================================

from testgen.mcp.tools.common import SCORE_FILTER_FIELD_TO_COLUMN
from testgen.mcp.tools.quality_scores import _validate_filters

# --- A. Shape / required-field rejections ---


def test_validate_filters_case_01_empty_list_rejected():
    # case 1
    with pytest.raises(MCPUserError, match=r"At least one filter is required\."):
        _validate_filters([])


def test_validate_filters_case_02_missing_field_key_rejected():
    # case 2
    with pytest.raises(MCPUserError, match=r"filters\[0\].*field.*value"):
        _validate_filters([{"value": "tg1"}])


def test_validate_filters_case_03_missing_value_key_rejected():
    # case 3
    with pytest.raises(MCPUserError, match=r"filters\[0\].*field.*value"):
        _validate_filters([{"field": "Table Group"}])


def test_validate_filters_case_04_empty_string_field_rejected():
    # case 4
    with pytest.raises(MCPUserError, match=r"filters\[0\].*field.*value"):
        _validate_filters([{"field": "", "value": "tg1"}])


def test_validate_filters_case_05_empty_string_value_rejected():
    # case 5
    with pytest.raises(MCPUserError, match=r"filters\[0\].*field.*value"):
        _validate_filters([{"field": "Table Group", "value": ""}])


def test_validate_filters_case_06_none_field_rejected():
    # case 6
    with pytest.raises(MCPUserError, match=r"filters\[0\].*field.*value"):
        _validate_filters([{"field": None, "value": "tg1"}])


def test_validate_filters_case_07_none_value_rejected():
    # case 7
    with pytest.raises(MCPUserError, match=r"filters\[0\].*field.*value"):
        _validate_filters([{"field": "Table Group", "value": None}])


def test_validate_filters_case_08_second_filter_malformed_indexed_at_1():
    # case 8 — index propagation through enumerate
    with pytest.raises(MCPUserError, match=r"filters\[1\]"):
        _validate_filters([
            {"field": "Table Group", "value": "tg1"},
            {"field": "Table Group"},
        ])


# --- B. SQL-injection value guard (flat path) ---


def test_validate_filters_case_09_value_with_single_quote_rejected():
    # case 9
    with pytest.raises(MCPUserError, match="forbidden"):
        _validate_filters([{"field": "Table Group", "value": "tg1' OR '1'='1"}])


def test_validate_filters_case_10_value_with_double_quote_rejected():
    # case 10
    with pytest.raises(MCPUserError, match="forbidden"):
        _validate_filters([{"field": "Table Group", "value": 'tg1"'}])


def test_validate_filters_case_11_value_with_semicolon_rejected():
    # case 11
    with pytest.raises(MCPUserError, match="forbidden"):
        _validate_filters([{"field": "Table Group", "value": "tg1; DROP"}])


def test_validate_filters_case_12_value_with_backslash_rejected():
    # case 12
    with pytest.raises(MCPUserError, match="forbidden"):
        _validate_filters([{"field": "Table Group", "value": "tg1\\foo"}])


def test_validate_filters_case_13_value_with_null_byte_rejected():
    # case 13
    with pytest.raises(MCPUserError, match="forbidden"):
        _validate_filters([{"field": "Table Group", "value": "tg1\x00"}])


def test_validate_filters_case_14_value_length_257_rejected():
    # case 14 — boundary: 257 > 256 limit
    with pytest.raises(MCPUserError, match="too long"):
        _validate_filters([{"field": "Table Group", "value": "x" * 257}])


def test_validate_filters_case_15_value_length_256_accepted():
    # case 15 — boundary: 256 == limit, accepted
    parsed, group_by_field = _validate_filters(
        [{"field": "Table Group", "value": "x" * 256}]
    )
    assert group_by_field is True
    assert parsed[0]["field"] == "table_groups_name"
    assert parsed[0]["value"] == "x" * 256


@pytest.mark.parametrize(
    "bad_value",
    [123, [1, 2], {"k": "v"}, True],
    ids=["case_16_int", "case_16_list", "case_16_dict", "case_16_bool"],
)
def test_validate_filters_case_16_value_non_string_rejected(bad_value):
    # case 16
    with pytest.raises(MCPUserError, match="must be a string"):
        _validate_filters([{"field": "Table Group", "value": bad_value}])


# --- C. Mode 1 (flat, no others) — happy paths ---


def test_validate_filters_case_17_single_table_group_flat():
    # case 17
    parsed, group_by_field = _validate_filters(
        [{"field": "Table Group", "value": "tg1"}]
    )
    assert group_by_field is True
    assert parsed == [{"field": "table_groups_name", "value": "tg1"}]


def test_validate_filters_case_18_two_filters_same_field():
    # case 18 — same display field, two values
    parsed, group_by_field = _validate_filters([
        {"field": "Table Group", "value": "tg1"},
        {"field": "Table Group", "value": "tg2"},
    ])
    assert group_by_field is True
    assert parsed == [
        {"field": "table_groups_name", "value": "tg1"},
        {"field": "table_groups_name", "value": "tg2"},
    ]


def test_validate_filters_case_19_two_filters_different_fields():
    # case 19 — different display fields
    parsed, group_by_field = _validate_filters([
        {"field": "Table Group", "value": "tg1"},
        {"field": "Data Source", "value": "Postgres"},
    ])
    assert group_by_field is True
    assert parsed == [
        {"field": "table_groups_name", "value": "tg1"},
        {"field": "data_source", "value": "Postgres"},
    ]


@pytest.mark.parametrize(
    "field_enum",
    list(ScoreFilterField),
    ids=[f"case_20_{f.name}" for f in ScoreFilterField],
)
def test_validate_filters_case_20_every_score_filter_field_accepted(field_enum):
    # case 20 — parametrize over every ScoreFilterField; assert translation
    parsed, group_by_field = _validate_filters(
        [{"field": field_enum.value, "value": "val"}]
    )
    assert group_by_field is True
    assert parsed[0]["field"] == SCORE_FILTER_FIELD_TO_COLUMN[field_enum]
    assert parsed[0]["value"] == "val"


# --- D. Mode 1 rejection paths ---


def test_validate_filters_case_21_column_form_field_rejected():
    # case 21 — column-form `data_source` must be rejected; error lists display values
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{"field": "data_source", "value": "Postgres"}])
    msg = exc_info.value.args[0]
    assert "Data Source" in msg
    # Column-form must NOT appear as a "valid" suggestion
    assert "`data_source`" in msg  # the rejected value is quoted back


def test_validate_filters_case_22_lowercase_quality_dimension_rejected():
    # case 22 — case-sensitive enum lookup
    with pytest.raises(MCPUserError, match="quality dimension"):
        _validate_filters([{"field": "quality dimension", "value": "Validity"}])


def test_validate_filters_case_23_quality_dimension_rejected_as_filter_field():
    # case 23 — valid group_by, not a valid filter field
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{"field": "Quality Dimension", "value": "Validity"}])
    assert "Quality Dimension" in exc_info.value.args[0]


def test_validate_filters_case_24_impact_dimension_rejected_as_filter_field():
    # case 24
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{"field": "Impact Dimension", "value": "High"}])
    assert "Impact Dimension" in exc_info.value.args[0]


def test_validate_filters_case_25_invalid_field_xyz_rejected():
    # case 25 — totally bogus field
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{"field": "xyz", "value": "v"}])
    msg = exc_info.value.args[0]
    assert "xyz" in msg
    # Error should list display-form values
    assert "Table Group" in msg


def test_validate_filters_case_26_empty_others_list_still_mode_1():
    # case 26 — others=[] is falsy in any(...)
    parsed, group_by_field = _validate_filters(
        [{"field": "Table Group", "value": "tg1", "others": []}]
    )
    assert group_by_field is True
    assert parsed[0]["field"] == "table_groups_name"


def test_validate_filters_case_27_none_others_still_mode_1():
    # case 27 — others=None is falsy in any(...)
    parsed, group_by_field = _validate_filters(
        [{"field": "Table Group", "value": "tg1", "others": None}]
    )
    assert group_by_field is True
    assert parsed[0]["field"] == "table_groups_name"


# --- E. Mode 2 (chained) — happy paths ---


def test_validate_filters_case_28_single_chain_one_step_table():
    # case 28 — Table Group → Table
    parsed, group_by_field = _validate_filters([{
        "field": "Table Group",
        "value": "tg1",
        "others": [{"field": "Table", "value": "orders"}],
    }])
    assert group_by_field is False
    assert parsed == [{
        "field": "table_groups_name",
        "value": "tg1",
        "others": [{"field": "table_name", "value": "orders"}],
    }]


def test_validate_filters_case_29_single_chain_two_steps_table_column():
    # case 29 — Table Group → Table → Column
    parsed, group_by_field = _validate_filters([{
        "field": "Table Group",
        "value": "tg1",
        "others": [
            {"field": "Table", "value": "orders"},
            {"field": "Column", "value": "id"},
        ],
    }])
    assert group_by_field is False
    assert parsed[0]["others"] == [
        {"field": "table_name", "value": "orders"},
        {"field": "column_name", "value": "id"},
    ]


def test_validate_filters_case_30_mode_2_with_sibling_flat_table_group():
    # case 30 — chain-having filter + bare Table Group (entire-tg case)
    parsed, group_by_field = _validate_filters([
        {
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "Table", "value": "orders"}],
        },
        {"field": "Table Group", "value": "tg2"},
    ])
    assert group_by_field is False
    assert len(parsed) == 2
    assert parsed[1]["field"] == "table_groups_name"
    assert parsed[1]["value"] == "tg2"


def test_validate_filters_case_31_multiple_chained_filters_same_shape():
    # case 31 — sibling OR semantics, both translated
    parsed, group_by_field = _validate_filters([
        {
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "Table", "value": "orders"}],
        },
        {
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "Table", "value": "customers"}],
        },
    ])
    assert group_by_field is False
    assert len(parsed) == 2
    for filter_ in parsed:
        assert filter_["field"] == "table_groups_name"
        assert filter_["others"][0]["field"] == "table_name"


def test_validate_filters_case_32_chain_leaf_value_length_256_accepted():
    # case 32 — boundary at chain leaf
    parsed, group_by_field = _validate_filters([{
        "field": "Table Group",
        "value": "tg1",
        "others": [{"field": "Table", "value": "x" * 256}],
    }])
    assert group_by_field is False
    assert parsed[0]["others"][0]["value"] == "x" * 256


# --- F. Mode 2 rejection paths ---


def test_validate_filters_case_33_root_not_table_group_with_others_rejected():
    # case 33 — has others but root is Data Source
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{
            "field": "Data Source",
            "value": "S",
            "others": [{"field": "Table", "value": "x"}],
        }])
    assert "Table Group" in exc_info.value.args[0]


def test_validate_filters_case_34_sibling_with_data_source_root_in_chain_mode_rejected():
    # case 34 — one filter chains; sibling has Data Source root (no chain) → reject
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([
            {
                "field": "Table Group",
                "value": "tg1",
                "others": [{"field": "Table", "value": "orders"}],
            },
            {"field": "Data Source", "value": "Postgres"},
        ])
    assert "Table Group" in exc_info.value.args[0]


def test_validate_filters_case_35_column_without_preceding_table_rejected():
    # case 35
    with pytest.raises(MCPUserError, match="`Column` chain requires a `Table` step"):
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "Column", "value": "id"}],
        }])


def test_validate_filters_case_36_chain_order_column_then_table_rejected():
    # case 36
    with pytest.raises(MCPUserError, match="`Column` must be the final chain step"):
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [
                {"field": "Column", "value": "id"},
                {"field": "Table", "value": "orders"},
            ],
        }])


def test_validate_filters_case_37_chain_leaf_column_form_table_name_rejected():
    # case 37 — column-form leaf `table_name` rejected (display-form only)
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "table_name", "value": "orders"}],
        }])
    msg = exc_info.value.args[0]
    assert "table_name" in msg  # the rejected field is quoted in the error
    # Valid leaves listed in display form
    assert "Table" in msg
    assert "Column" in msg


def test_validate_filters_case_38_invalid_chain_leaf_field_rejected():
    # case 38
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "something_else", "value": "v"}],
        }])
    msg = exc_info.value.args[0]
    assert "something_else" in msg
    assert "Table" in msg
    assert "Column" in msg


def test_validate_filters_case_39_chain_leaf_missing_field_rejected():
    # case 39 — indexed filters[0].others[0]
    with pytest.raises(MCPUserError, match=r"filters\[0\]\.others\[0\].*field.*value"):
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [{"value": "orders"}],
        }])


def test_validate_filters_case_40_chain_leaf_missing_value_rejected():
    # case 40 — indexed filters[0].others[0]
    with pytest.raises(MCPUserError, match=r"filters\[0\]\.others\[0\].*field.*value"):
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "Table"}],
        }])


def test_validate_filters_case_41_chain_leaf_value_with_forbidden_char_rejected():
    # case 41 — indexed
    with pytest.raises(MCPUserError, match=r"filters\[0\]\.others\[0\].*forbidden"):
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "Table", "value": "x'; DROP"}],
        }])


def test_validate_filters_case_42_chain_leaf_value_too_long_rejected():
    # case 42 — indexed
    with pytest.raises(MCPUserError, match=r"filters\[0\]\.others\[0\].*too long"):
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "Table", "value": "x" * 300}],
        }])


def test_validate_filters_case_43_chain_leaf_value_non_string_rejected():
    # case 43 — indexed
    with pytest.raises(MCPUserError, match=r"filters\[0\]\.others\[0\].*must be a string"):
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "Table", "value": 123}],
        }])


def test_validate_filters_case_44_chain_with_extra_trailing_column_rejected():
    # case 44 — Table → Column → Column: second Column is in prefix, not the end
    with pytest.raises(MCPUserError, match="`Column` must be the final chain step"):
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [
                {"field": "Table", "value": "orders"},
                {"field": "Column", "value": "id"},
                {"field": "Column", "value": "name"},
            ],
        }])


# --- G. Translation correctness (output-shape) ---


def test_validate_filters_case_45_output_has_only_column_form_keys():
    # case 45 — every returned `field` is column-form
    parsed, _ = _validate_filters([
        {"field": "Table Group", "value": "tg1"},
        {"field": "Data Source", "value": "Postgres"},
        {"field": "Quality Dimension", "value": "ignored"},  # would fail; remove
    ][:2])  # only the first two — Quality Dimension isn't a valid filter
    column_form_field_values = set(SCORE_FILTER_FIELD_TO_COLUMN.values()) | {
        "table_name", "column_name",
    }
    for filter_ in parsed:
        assert filter_["field"] in column_form_field_values

    # Also test chain leaves
    parsed_chain, _ = _validate_filters([{
        "field": "Table Group",
        "value": "tg1",
        "others": [
            {"field": "Table", "value": "orders"},
            {"field": "Column", "value": "id"},
        ],
    }])
    for filter_ in parsed_chain:
        assert filter_["field"] in column_form_field_values
        for leaf in filter_.get("others", []):
            assert leaf["field"] in column_form_field_values


def test_validate_filters_case_46_values_byte_identical_to_input():
    # case 46 — values are NEVER mutated by translation
    raw = [{
        "field": "Table Group",
        "value": "MixedCaseTG.with-dots_underscores",
        "others": [
            {"field": "Table", "value": "Orders Table"},
            {"field": "Column", "value": "ID-Col"},
        ],
    }]
    parsed, _ = _validate_filters(raw)
    assert parsed[0]["value"] == "MixedCaseTG.with-dots_underscores"
    assert parsed[0]["others"][0]["value"] == "Orders Table"
    assert parsed[0]["others"][1]["value"] == "ID-Col"


def test_validate_filters_case_47_group_by_field_flag_correct():
    # case 47 — True iff no filter has non-empty others
    _, flag_flat = _validate_filters([{"field": "Table Group", "value": "tg1"}])
    assert flag_flat is True
    _, flag_chained = _validate_filters([{
        "field": "Table Group",
        "value": "tg1",
        "others": [{"field": "Table", "value": "orders"}],
    }])
    assert flag_chained is False


# --- H. Error-message hygiene (regression guards) ---


def test_validate_filters_case_48_flat_error_message_uses_display_form():
    # case 48 — error mentions valid flat fields: at least one display-form value;
    # no underscore-form column names
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{"field": "xyz", "value": "v"}])
    msg = exc_info.value.args[0]
    assert "Table Group" in msg  # display-form present
    # None of the column-form values should appear as a "valid" suggestion
    # (the rejected `xyz` is fine; we're checking valid-values listing)
    column_form_values = set(SCORE_FILTER_FIELD_TO_COLUMN.values())
    for col_value in column_form_values:
        # Each column-form value (e.g. "table_groups_name", "data_source") must
        # not appear in the listed-valid set. The rejected field name is also
        # mentioned, but that's a user-supplied string, not "xyz" matching.
        assert col_value not in msg, (
            f"Error message must not list column-form `{col_value}` as a valid value. "
            f"Full message: {msg}"
        )


def test_validate_filters_case_49_chain_leaf_error_uses_display_form():
    # case 49 — leaf error mentions Table and Column, not table_name/column_name
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [{"field": "something_else", "value": "v"}],
        }])
    msg = exc_info.value.args[0]
    assert "Table" in msg
    assert "Column" in msg
    # The column-form leaf names must not appear as "valid" leaves
    assert "table_name" not in msg.replace("`Table`", "").replace("Table", "")  # `Table` ok, `table_name` not
    assert "column_name" not in msg.replace("`Column`", "").replace("Column", "")


# --- Wrapper-level: column-form rejected through create_scorecard ---


def test_create_scorecard_rejects_column_form_field_through_wrapper(db_session_mock):
    # case 21 mirrored at the MCP wrapper level
    from testgen.mcp.tools.quality_scores import create_scorecard

    with (
        _patch_perms(),
        _patch_orchestrator() as mock_orch,
        pytest.raises(MCPUserError) as exc_info,
    ):
        create_scorecard(
            "demo",
            "My Card",
            filters=[{"field": "data_source", "value": "Postgres"}],
        )
    msg = exc_info.value.args[0]
    assert "Data Source" in msg
    mock_orch.assert_not_called()


# ============================================================
# Unified validator: allow_empty + multi-error collection
# ============================================================


def test_validate_filters_empty_default_rejected():
    """With the default allow_empty=False, an empty list raises."""
    with pytest.raises(MCPUserError, match=r"At least one filter is required\."):
        _validate_filters([])


def test_validate_filters_none_default_rejected():
    """With the default allow_empty=False, None raises."""
    with pytest.raises(MCPUserError, match=r"At least one filter is required\."):
        _validate_filters(None)


def test_validate_filters_empty_allowed_returns_empty_tuple():
    """allow_empty=True short-circuits an empty list to ([], True)."""
    parsed, group_by_field = _validate_filters([], allow_empty=True)
    assert parsed == []
    assert group_by_field is True


def test_validate_filters_none_allowed_returns_empty_tuple():
    """allow_empty=True short-circuits None to ([], True)."""
    parsed, group_by_field = _validate_filters(None, allow_empty=True)
    assert parsed == []
    assert group_by_field is True


def test_validate_filters_collects_multiple_flat_errors():
    """Multi-error collection: every offending entry is named in the message."""
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([
            {"field": "Quality Dimension", "value": "Accuracy"},  # not a filter field
            {"field": "Business Domain", "value": "x';--"},       # forbidden chars
            {"field": "Data Source", "value": ""},                # empty value
        ])
    msg = exc_info.value.args[0]
    assert "Quality Dimension" in msg
    assert "Business Domain" in msg
    assert "Data Source" in msg


def test_validate_filters_collects_multiple_chain_leaf_errors():
    """Chain-mode also collects per-leaf errors instead of stopping at the first."""
    with pytest.raises(MCPUserError) as exc_info:
        _validate_filters([{
            "field": "Table Group",
            "value": "tg1",
            "others": [
                {"field": "bogus_leaf", "value": "x"},        # invalid leaf field
                {"field": "Table", "value": "tbl';DROP"},     # forbidden char in valid leaf
            ],
        }])
    msg = exc_info.value.args[0]
    assert "bogus_leaf" in msg
    assert "forbidden" in msg


# ============================================================
# get_quality_scores: mode-2 chained filter support
# ============================================================


@patch("testgen.mcp.tools.quality_scores.ScoreDefinitionCriteria")
@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_get_quality_scores_accepts_mode_2_chained_filters(
    mock_definition_cls, mock_criteria_cls, db_session_mock,
):
    """A chained Table Group → Table filter reaches from_filters with group_by_field=False."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        get_quality_scores(
            project_code="demo",
            filters=[{
                "field": "Table Group",
                "value": "tg1",
                "others": [{"field": "Table", "value": "orders"}],
            }],
        )

    mock_criteria_cls.from_filters.assert_called_once()
    args, kwargs = mock_criteria_cls.from_filters.call_args
    passed = args[0]
    assert kwargs.get("group_by_field") is False
    assert passed[0]["field"] == "table_groups_name"
    assert passed[0]["value"] == "tg1"
    assert passed[0]["others"] == [{"field": "table_name", "value": "orders"}]


def test_get_quality_scores_rejects_table_group_id_with_chained_filters(db_session_mock):
    """table_group_id + a mode-2 chain conflict — the implicit name filter would
    shadow the chain root, so reject explicitly."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    tg = MagicMock()
    tg.id = uuid4()
    tg.project_code = "demo"
    tg.table_groups_name = "orders_tg"

    with (
        _patch_perms(),
        patch("testgen.mcp.tools.common.TableGroup") as mock_tg_cls,
        pytest.raises(MCPUserError, match="chained filters"),
    ):
        mock_tg_cls.get.return_value = tg
        get_quality_scores(
            table_group_id=str(tg.id),
            filters=[{
                "field": "Table Group",
                "value": "tg1",
                "others": [{"field": "Table", "value": "orders"}],
            }],
        )


# --- Filter documentation ---


def test_filter_shape_doc_lists_every_filter_field():
    """The shared `filters` documentation names each field the validator accepts.

    The field labels are written out in prose because they are published to clients as a
    schema description, so nothing but this test ties them to the enum.
    """
    missing = [field.value for field in ScoreFilterField if f'"{field.value}"' not in _FILTER_SHAPE_DOC]
    assert not missing, f"Filter fields accepted by _validate_filters but undocumented: {missing}"

    chain_only = [field.value for field in ScoreChainLeafField if f'"{field.value}"' not in _FILTER_SHAPE_DOC]
    assert not chain_only, f"Chain leaf fields undocumented: {chain_only}"
