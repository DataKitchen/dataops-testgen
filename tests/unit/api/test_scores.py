"""Tests for testgen.api.scores — quality-score rollup endpoint."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.enums import ScoresGroupBy, ScoreType
from testgen.api.scores import (
    _build_filter_list,
    _scale_score,
    _translate_group_value,
    get_project_scores,
    router,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.api.scores"


def _call(**overrides):
    """Invoke ``get_project_scores`` with every dependency-resolved arg explicit.

    Direct-invocation tests must pass Query() params by hand because FastAPI's
    resolver isn't in the loop."""
    kwargs = {
        "project_code": "demo",
        "group_by": None,
        "score_type": ScoreType.total,
        "data_source": None,
        "business_domain": None,
        "source_system": None,
        "source_process": None,
        "stakeholder_group": None,
        "transform_level": None,
        "data_location": None,
        "data_product": None,
        "semantic_data_type": None,
        "data_classification": None,
    }
    kwargs.update(overrides)
    return get_project_scores(**kwargs)


def _score_card(**overrides) -> dict:
    """Return a fake ScoreCard TypedDict."""
    defaults = {
        "id": uuid4(),
        "project_code": "demo",
        "name": "__api_scores__",
        "score": 0.95,
        "cde_score": 0.87,
        "profiling_score": 0.98,
        "testing_score": 0.97,
        "categories": [],
        "history": [],
        "definition": None,
    }
    defaults.update(overrides)
    return defaults


# --- Handler: overall response ---


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_overall_only_scales_to_zero_to_hundred(mock_def_cls):
    """Without a group_by, response has scaled overall scores and no breakdown."""
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card(
        score=0.95,
        cde_score=0.87,
        profiling_score=0.98,
        testing_score=0.97,
    )
    mock_def_cls.return_value = mock_def

    resp = _call()

    assert resp.total == pytest.approx(95.0)
    assert resp.cde == pytest.approx(87.0)
    assert resp.profiling == pytest.approx(98.0)
    assert resp.testing == pytest.approx(97.0)
    assert resp.breakdown is None
    mock_def.get_score_card_breakdown.assert_not_called()


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_null_score_stays_null(mock_def_cls):
    """Missing scores from the engine surface as ``null``, not 0."""
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card(
        score=None, cde_score=None, profiling_score=None, testing_score=None,
    )
    mock_def_cls.return_value = mock_def

    resp = _call()

    assert resp.total is None
    assert resp.cde is None
    assert resp.profiling is None
    assert resp.testing is None


# --- Handler: group_by breakdown ---


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_group_by_impact_dimension_translates_and_orders(mock_def_cls):
    """Engine returns title-case dimension values ordered by impact; the API emits
    lowercase enum members and preserves the order."""
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def.get_score_card_breakdown.return_value = [
        {"impact_dimension": "Reliability", "score": 0.6, "impact": 40.0, "issue_ct": 12},
        {"impact_dimension": "Conformance", "score": 0.9, "impact": 5.0, "issue_ct": 1},
    ]
    mock_def_cls.return_value = mock_def

    resp = _call(group_by=ScoresGroupBy.impact_dimension)

    assert resp.breakdown is not None
    assert [row.value for row in resp.breakdown] == ["reliability", "conformance"]
    assert [row.impact for row in resp.breakdown] == [40.0, 5.0]
    assert resp.breakdown[0].score == pytest.approx(60.0)
    assert resp.breakdown[1].score == pytest.approx(90.0)


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_group_by_quality_dimension_translates_labels(mock_def_cls):
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def.get_score_card_breakdown.return_value = [
        {"dq_dimension": "Accuracy", "score": 0.5, "impact": 30.0, "issue_ct": 3},
    ]
    mock_def_cls.return_value = mock_def

    resp = _call(group_by=ScoresGroupBy.quality_dimension)

    assert resp.breakdown[0].value == "accuracy"


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_group_by_data_source_passes_value_through(mock_def_cls):
    """Non-dimension group_by values are passed through as-is."""
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def.get_score_card_breakdown.return_value = [
        {"data_source": "sales_db", "score": 0.9, "impact": 12.5, "issue_ct": 2},
    ]
    mock_def_cls.return_value = mock_def

    resp = _call(group_by=ScoresGroupBy.data_source)

    assert resp.breakdown[0].value == "sales_db"


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_null_group_value_surfaces_as_none(mock_def_cls):
    """Rows with a null grouping column (e.g. an issue type with no
    ``impact_dimension``) surface as ``value: null`` — not empty string."""
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def.get_score_card_breakdown.return_value = [
        {"impact_dimension": "Reliability", "score": 0.6, "impact": 40.0, "issue_ct": 3},
        {"impact_dimension": None, "score": 0.8, "impact": 10.0, "issue_ct": 1},
    ]
    mock_def_cls.return_value = mock_def

    resp = _call(group_by=ScoresGroupBy.impact_dimension)

    assert [row.value for row in resp.breakdown] == ["reliability", None]


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_group_by_table_group_uses_engine_category(mock_def_cls):
    """API ``table_group`` maps to the engine's ``table_groups_name`` column."""
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def.get_score_card_breakdown.return_value = [
        {"table_groups_name": "orders", "score": 0.8, "impact": 20.0, "issue_ct": 5},
    ]
    mock_def_cls.return_value = mock_def

    resp = _call(group_by=ScoresGroupBy.table_group)

    assert resp.breakdown[0].value == "orders"
    call = mock_def.get_score_card_breakdown.call_args
    assert call.kwargs["group_by"] == "table_groups_name"


# --- Handler: score_type forwarding ---


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_score_type_cde_calls_breakdown_with_cde_score(mock_def_cls):
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def.get_score_card_breakdown.return_value = []
    mock_def_cls.return_value = mock_def

    _call(group_by=ScoresGroupBy.impact_dimension, score_type=ScoreType.cde)

    assert mock_def.get_score_card_breakdown.call_args.kwargs["score_type"] == "cde_score"


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_score_type_total_calls_breakdown_with_score(mock_def_cls):
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def.get_score_card_breakdown.return_value = []
    mock_def_cls.return_value = mock_def

    _call(group_by=ScoresGroupBy.impact_dimension, score_type=ScoreType.total)

    assert mock_def.get_score_card_breakdown.call_args.kwargs["score_type"] == "score"


# --- Handler: filter forwarding ---


@patch(f"{MODULE}.ScoreDefinitionCriteria")
@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_forwards_filters_repeatable_and_flat(mock_def_cls, mock_criteria_cls):
    """Repeated data_source values and a single business_domain value flatten into
    the ``[{field, value}]`` shape ``from_filters`` expects."""
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def_cls.return_value = mock_def

    _call(
        data_source=["sales_db", "warehouse"],
        business_domain=["finance"],
    )

    filters, = mock_criteria_cls.from_filters.call_args.args
    assert filters == [
        {"field": "data_source", "value": "sales_db"},
        {"field": "data_source", "value": "warehouse"},
        {"field": "business_domain", "value": "finance"},
    ]
    assert mock_criteria_cls.from_filters.call_args.kwargs == {"group_by_field": True}


@patch(f"{MODULE}.ScoreDefinitionCriteria")
@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_no_filters_forwards_empty_list(mock_def_cls, mock_criteria_cls):
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def_cls.return_value = mock_def

    _call()

    assert mock_criteria_cls.from_filters.call_args.args == ([],)


# --- Handler: empty results are 200 with empty breakdown ---


@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_zero_match_returns_empty_breakdown(mock_def_cls):
    """Filters that match nothing still 200 — empty breakdown, no 404."""
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card(
        score=None, cde_score=None, profiling_score=None, testing_score=None,
    )
    mock_def.get_score_card_breakdown.return_value = []
    mock_def_cls.return_value = mock_def

    resp = _call(group_by=ScoresGroupBy.data_source, data_source=["doesntexist"])

    assert resp.total is None
    assert resp.breakdown == []


# --- Helpers ---


def test_scale_score_none_stays_none():
    assert _scale_score(None) is None


def test_scale_score_fraction_to_percent():
    assert _scale_score(0.87) == pytest.approx(87.0)
    assert _scale_score(0.0) == pytest.approx(0.0)
    assert _scale_score(1.0) == pytest.approx(100.0)


def test_translate_group_value_impact_dimension_lowercases():
    assert _translate_group_value(ScoresGroupBy.impact_dimension, "Reliability") == "reliability"
    assert _translate_group_value(ScoresGroupBy.impact_dimension, "Conformance") == "conformance"


def test_translate_group_value_quality_dimension_lowercases():
    assert _translate_group_value(ScoresGroupBy.quality_dimension, "Accuracy") == "accuracy"


def test_translate_group_value_non_dimension_passes_through():
    assert _translate_group_value(ScoresGroupBy.data_source, "sales_db") == "sales_db"


def test_translate_group_value_null_stays_null():
    assert _translate_group_value(ScoresGroupBy.data_source, None) is None
    assert _translate_group_value(ScoresGroupBy.impact_dimension, None) is None


def test_build_filter_list_drops_empty_and_none():
    out = _build_filter_list(
        data_source=["a", "b"],
        business_domain=None,
        source_system=[],
        stakeholder_group=["ops"],
    )
    assert out == [
        {"field": "data_source", "value": "a"},
        {"field": "data_source", "value": "b"},
        {"field": "stakeholder_group", "value": "ops"},
    ]


@pytest.mark.parametrize(
    "bad_value",
    [
        "' OR 1=1--",
        'x"; DROP TABLE',
        "\\n",
        "with\x00null",
    ],
)
def test_build_filter_list_rejects_forbidden_characters(bad_value):
    """Values feed into raw-SQL interpolation downstream; forbidden chars are 400s."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _build_filter_list(data_source=[bad_value])
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["errors"][0]["code"] == "invalid_filter_value"


def test_build_filter_list_rejects_overlong_value():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _build_filter_list(data_source=["a" * 257])
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["errors"][0]["code"] == "invalid_filter_value"


def test_build_filter_list_accepts_data_classification():
    """data_classification is a valid filter field alongside the other nine."""
    out = _build_filter_list(data_classification=["Confidential"])
    assert out == [{"field": "data_classification", "value": "Confidential"}]


# --- HTTP-level query validation ---


def _client_with_overrides() -> FastAPI:
    """Build a TestClient app that bypasses auth and db_session so query validation runs unimpeded."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[db_session] = lambda: iter([None])
    app.dependency_overrides[get_authorized_user] = lambda: MagicMock(id=uuid4())
    return app


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_rejects_unknown_group_by(mock_def_cls, _mock_perm):
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def_cls.return_value = mock_def
    client = TestClient(_client_with_overrides())

    resp = client.get("/api/v1/projects/demo/scores?group_by=column_name")

    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"][0]["loc"] == ["query", "group_by"]
    assert body["detail"][0]["type"] == "enum"


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_rejects_unknown_score_type(mock_def_cls, _mock_perm):
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def_cls.return_value = mock_def
    client = TestClient(_client_with_overrides())

    resp = client.get("/api/v1/projects/demo/scores?score_type=bogus")

    assert resp.status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.ScoreDefinition")
def test_get_project_scores_accepts_repeated_filter_values(mock_def_cls, _mock_perm):
    mock_def = MagicMock()
    mock_def.as_score_card.return_value = _score_card()
    mock_def.get_score_card_breakdown.return_value = []
    mock_def_cls.return_value = mock_def
    client = TestClient(_client_with_overrides())

    resp = client.get(
        "/api/v1/projects/demo/scores?data_source=a&data_source=b&business_domain=finance",
    )

    assert resp.status_code == 200


@patch("testgen.api.deps.has_project_permission", return_value=False)
def test_get_project_scores_denies_without_permission(_mock_perm):
    """No membership / insufficient role — uniform 404."""
    client = TestClient(_client_with_overrides())

    resp = client.get("/api/v1/projects/demo/scores")

    assert resp.status_code == 404
    assert resp.json()["detail"]["errors"][0]["code"] == "not_found"
