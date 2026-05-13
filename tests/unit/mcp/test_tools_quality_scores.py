from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

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
    memberships = memberships or {code: "role_a" for code in allowed}
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
    assert "Combined" in msg
    assert "CDE" in msg


@pytest.mark.parametrize("internal", ["total", "cde"])
def test_internal_score_type_rejected(internal, db_session_mock):
    """``total``/``cde`` were the old internal codes — inputs now use ``Combined``/``CDE``."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="Invalid score_type"):
        get_quality_scores(project_code="demo", score_type=internal)


def test_invalid_filter_field_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="Invalid filter field"):
        get_quality_scores(
            project_code="demo",
            filters=[{"field": "not_a_field", "value": "x"}],
        )


def test_internal_filter_field_rejected(db_session_mock):
    """Old internal column name as filter field is no longer accepted."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="Invalid filter field"):
        get_quality_scores(
            project_code="demo",
            filters=[{"field": "business_domain", "value": "Finance"}],
        )


def test_quality_dimension_rejected_as_filter_field(db_session_mock):
    """Quality Dimension is a group_by, not a filter field — must reject with a hint."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="Quality Dimension") as exc_info:
        get_quality_scores(
            project_code="demo",
            filters=[{"field": "Quality Dimension", "value": "Accuracy"}],
        )
    assert "group_by" in str(exc_info.value)


def test_impact_dimension_rejected_as_filter_field(db_session_mock):
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="Impact Dimension") as exc_info:
        get_quality_scores(
            project_code="demo",
            filters=[{"field": "Impact Dimension", "value": "Workflow"}],
        )
    assert "group_by" in str(exc_info.value)


def test_filter_value_with_forbidden_chars_rejected(db_session_mock):
    """SQL-injection probe — values with single quotes or semicolons must be rejected."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="forbidden"):
        get_quality_scores(
            project_code="demo",
            filters=[{"field": "Business Domain", "value": "O';DROP TABLE"}],
        )


def test_filter_value_oversize_rejected(db_session_mock):
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(), pytest.raises(MCPUserError, match="too long"):
        get_quality_scores(
            project_code="demo",
            filters=[{"field": "Business Domain", "value": "x" * 257}],
        )


def test_multiple_filter_problems_listed_at_once(db_session_mock):
    """When several filter entries are bad, the error lists every offender."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    bad_filters = [
        {"field": "Quality Dimension", "value": "Accuracy"},  # not a filter field
        {"field": "Business Domain", "value": "x';--"},       # bad chars
        {"field": "Data Source", "value": ""},                # empty value
    ]
    with _patch_perms(), pytest.raises(MCPUserError) as exc_info:
        get_quality_scores(project_code="demo", filters=bad_filters)

    msg = str(exc_info.value)
    assert "Quality Dimension" in msg
    assert "Business Domain" in msg
    assert "Data Source" in msg


def test_project_not_accessible_rejected(db_session_mock):
    """A project the user can't view raises MCPResourceNotAccessible-style error."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    with _patch_perms(allowed=("only_this",)), pytest.raises(MCPResourceNotAccessible, match="forbidden_proj"):
        get_quality_scores(project_code="forbidden_proj")


# --- Score-type → model-call mapping ---


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_default_overall_shows_both_combined_and_cde(mock_definition_cls, db_session_mock):
    """score_type omitted → both Combined and CDE Score lines are rendered."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.93, cde_score=0.81)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "Combined Score" in out
    assert "93" in out
    assert "CDE Score" in out
    assert "81" in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_combined_overall_shows_only_combined(mock_definition_cls, db_session_mock):
    """score_type='Combined' renders only the Combined Score line."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.93, cde_score=None)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        out = get_quality_scores(
            project_code="demo",
            score_type="Combined",
            filters=[{"field": "Business Domain", "value": "Finance"}],
        )

    assert "Combined Score" in out
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
    assert "Combined Score" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_combined_grouped_uses_breakdown(mock_definition_cls, db_session_mock):
    """score_type='Combined' + group_by sources per-category rows from breakdown.

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
            score_type="Combined",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "warehouse"}],
            include_impact=True,
        )

    mock_definition.get_score_card_breakdown.assert_called_once_with("score", "business_domain")
    assert "Finance" in out
    assert "Marketing" in out
    assert "Impact on Combined Score" in out
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
    assert "Impact on Combined Score" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_default_grouped_renders_both_score_columns(mock_definition_cls, db_session_mock):
    """score_type omitted + group_by → table has Combined + CDE columns and
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

    assert "Combined Score" in out
    assert "CDE Score" in out
    assert "Impact on Combined Score" in out
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
    assert "Combined Score" in out
    assert "CDE Score" in out
    assert "Impact" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_impact_false_combined_only_omits_impact_column(mock_definition_cls, db_session_mock):
    """Combined-only + default include_impact=False → no impact column."""
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
            score_type="Combined",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    assert "Finance" in out
    assert "Combined Score" in out
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
def test_include_issue_ct_grouped_combined_uses_simple_label(mock_definition_cls, db_session_mock):
    """grouped + Combined + include_issue_ct: single 'Issue Count' column header."""
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
            score_type="Combined",
            group_by="Business Domain",
            include_issue_ct=True,
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    mock_definition.get_score_card_breakdown.assert_called_once_with("score", "business_domain")
    assert "Finance" in out
    assert "7" in out
    assert "Issue Count" in out
    assert "Issue Count (Combined)" not in out
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
    assert "Issue Count (Combined)" not in out
    assert "Issue Count (CDE)" not in out


@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_include_issue_ct_grouped_default_uses_parenthetical_labels(mock_definition_cls, db_session_mock):
    """grouped + score_type unset + include_issue_ct: separate Combined / CDE
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
    assert "Issue Count (Combined)" in out
    assert "Issue Count (CDE)" in out
    assert "Impact on Combined Score" in out
    assert "Impact on CDE Score" in out
    # Both per-category issue counts must appear, not just one
    assert "7" in out  # combined count
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


@patch("testgen.mcp.tools.quality_scores.TableGroup")
@patch("testgen.mcp.tools.quality_scores.ScoreDefinition")
def test_unfiltered_project_enumerates_table_groups(mock_definition_cls, mock_tg_cls, db_session_mock):
    """Unfiltered project_code call enumerates table groups so as_score_card's
    has_filters() gate passes (mirrors the score-explorer UI default)."""
    from testgen.mcp.tools.quality_scores import get_quality_scores

    tg1 = MagicMock()
    tg1.table_groups_name = "orders"
    tg2 = MagicMock()
    tg2.table_groups_name = "customers"
    mock_tg_cls.select_minimal_where.return_value = [tg1, tg2]

    mock_definition = MagicMock()
    mock_definition.as_score_card.return_value = _score_card(score=0.9)
    mock_definition_cls.return_value = mock_definition

    with _patch_perms():
        get_quality_scores(project_code="demo")

    # Verify TableGroup.select_minimal_where was called for enumeration.
    mock_tg_cls.select_minimal_where.assert_called_once()


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
            score_type="Combined",
            group_by="Business Domain",
            filters=[{"field": "Data Source", "value": "wh"}],
        )

    assert f"Showing top {_ROW_CAP}" in out
    assert str(_ROW_CAP + 10) in out


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
