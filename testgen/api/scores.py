"""API v1 — quality-score rollups.

Exposes the Quality Score for a project — overall totals plus an optional
group_by breakdown ordered by impact."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from testgen.api.deps import api_error, db_session, resolve_project_code
from testgen.api.enums import (
    IMPACT_DIMENSION_FROM_DB,
    QUALITY_DIMENSION_FROM_DB,
    ScoresGroupBy,
    ScoreType,
)
from testgen.api.schemas import ErrorResponse, ScoreBreakdownRow, ScoresResponse
from testgen.common.enums import ImpactDimension as DbImpactDimension
from testgen.common.enums import QualityDimension as DbQualityDimension
from testgen.common.models.scores import (
    Categories,
    ScoreDefinition,
    ScoreDefinitionCriteria,
)

_error_responses = {
    404: {"model": ErrorResponse, "description": "Not found"},
}

router = APIRouter(tags=["Scores"], dependencies=[Depends(db_session)], responses=_error_responses)

# API ``group_by`` value → underlying score-engine category column.
# The engine's Categories literal uses ``dq_dimension`` and ``table_groups_name``;
# the API surfaces the user-friendly names.
_GROUP_BY_TO_ENGINE: dict[ScoresGroupBy, Categories] = {
    ScoresGroupBy.quality_dimension: "dq_dimension",
    ScoresGroupBy.impact_dimension: "impact_dimension",
    ScoresGroupBy.table_group: "table_groups_name",
    ScoresGroupBy.data_source: "data_source",
    ScoresGroupBy.business_domain: "business_domain",
    ScoresGroupBy.source_system: "source_system",
    ScoresGroupBy.source_process: "source_process",
    ScoresGroupBy.stakeholder_group: "stakeholder_group",
    ScoresGroupBy.transform_level: "transform_level",
    ScoresGroupBy.data_location: "data_location",
    ScoresGroupBy.data_product: "data_product",
    ScoresGroupBy.semantic_data_type: "semantic_data_type",
    ScoresGroupBy.data_classification: "data_classification",
}

# quality_dimension, impact_dimension, and table_group are groupable only, not filterable.
_FILTER_FIELDS: tuple[str, ...] = (
    "data_source",
    "business_domain",
    "source_system",
    "source_process",
    "stakeholder_group",
    "transform_level",
    "data_location",
    "data_product",
    "semantic_data_type",
    "data_classification",
)

# ``ScoreDefinitionCriteria.get_as_sql`` interpolates filter values into raw
# SQL (see ``testgen/common/models/scores.py``). Values reach this endpoint
# straight from the query string, so we validate every one before letting it
# through — matching the guard the MCP quality-scores tool applies.
_FILTER_VALUE_MAX_LEN = 256
_FILTER_VALUE_FORBIDDEN_CHARS = frozenset("'\";\\\x00")


@router.get(
    "/projects/{project_code}/scores",
    response_model=ScoresResponse,
    summary="Quality Score rollup for a project",
    responses={400: {"model": ErrorResponse, "description": "Invalid filter value"}},
)
def get_project_scores(
    project_code: str = resolve_project_code("view"),
    group_by: ScoresGroupBy | None = Query(default=None),  # noqa: B008
    score_type: ScoreType = Query(default=ScoreType.total),  # noqa: B008
    data_source: Annotated[list[str] | None, Query()] = None,
    business_domain: Annotated[list[str] | None, Query()] = None,
    source_system: Annotated[list[str] | None, Query()] = None,
    source_process: Annotated[list[str] | None, Query()] = None,
    stakeholder_group: Annotated[list[str] | None, Query()] = None,
    transform_level: Annotated[list[str] | None, Query()] = None,
    data_location: Annotated[list[str] | None, Query()] = None,
    data_product: Annotated[list[str] | None, Query()] = None,
    semantic_data_type: Annotated[list[str] | None, Query()] = None,
    data_classification: Annotated[list[str] | None, Query()] = None,
):
    """Quality Score rollup for a project.

    Returns the overall Testing Score (``total`` / ``cde`` / ``profiling`` / ``testing``).
    When ``group_by`` is supplied, adds a ``breakdown`` ordered by ``impact`` descending —
    the actionable signal for which group accounts for the most of the score's
    affected data points. ``impact_dimension`` is the recommended primary breakdown.

    Filter query params are repeatable: repeats within one field OR together, different
    fields AND together. ``quality_dimension``, ``impact_dimension`` and ``table_group``
    are groupable only, not filterable.
    """
    filters = _build_filter_list(
        data_source=data_source,
        business_domain=business_domain,
        source_system=source_system,
        source_process=source_process,
        stakeholder_group=stakeholder_group,
        transform_level=transform_level,
        data_location=data_location,
        data_product=data_product,
        semantic_data_type=semantic_data_type,
        data_classification=data_classification,
    )

    definition = ScoreDefinition(
        project_code=project_code,
        name="__api_scores__",
        total_score=True,
        cde_score=True,
        criteria=ScoreDefinitionCriteria.from_filters(filters, group_by_field=True),
    )
    card = definition.as_score_card()

    breakdown: list[ScoreBreakdownRow] | None = None
    if group_by is not None:
        engine_group_by = _GROUP_BY_TO_ENGINE[group_by]
        rows = definition.get_score_card_breakdown(
            score_type="cde_score" if score_type is ScoreType.cde else "score",
            group_by=engine_group_by,
        )
        breakdown = [
            ScoreBreakdownRow(
                value=_translate_group_value(group_by, row.get(engine_group_by)),
                score=_scale_score(row.get("score")),
                impact=row.get("impact", 0.0),
            )
            for row in rows
        ]

    return ScoresResponse(
        total=_scale_score(card.get("score")),
        cde=_scale_score(card.get("cde_score")),
        profiling=_scale_score(card.get("profiling_score")),
        testing=_scale_score(card.get("testing_score")),
        breakdown=breakdown,
    )


def _build_filter_list(**named_lists: list[str] | None) -> list[dict]:
    """Flatten repeated query params into the ``[{field, value}, ...]`` shape
    that ``ScoreDefinitionCriteria.from_filters`` accepts.

    Every value is validated first — filter values reach raw-SQL interpolation
    in ``ScoreDefinitionCriteria.get_as_sql``, so overlong or quote/backslash-
    bearing input is rejected with 400 rather than reaching the DB layer."""
    errors: list[str] = []
    out: list[dict] = []
    for field in _FILTER_FIELDS:
        for value in named_lists.get(field) or ():
            if len(value) > _FILTER_VALUE_MAX_LEN:
                errors.append(f"{field!r}: value too long ({len(value)} > {_FILTER_VALUE_MAX_LEN})")
                continue
            bad = sorted(set(value) & _FILTER_VALUE_FORBIDDEN_CHARS)
            if bad:
                errors.append(f"{field!r}: value contains forbidden characters {bad}")
                continue
            out.append({"field": field, "value": value})
    if errors:
        raise api_error(400, "invalid_filter_value", "; ".join(errors))
    return out


def _scale_score(raw: float | None) -> float | None:
    """Engine scores are 0-1 fractions; the API surfaces 0-100 like the UI does."""
    if raw is None:
        return None
    return raw * 100


def _translate_group_value(group_by: ScoresGroupBy, raw_value: object) -> str | None:
    """Map the engine's stored dimension value (title-case) to the lowercase API enum.
    Other group_by values pass through as strings; NULLs stay NULL — a caller sees
    "some scored data isn't classified into this group"."""
    if raw_value is None:
        return None
    if group_by is ScoresGroupBy.impact_dimension:
        return _dimension_to_api(raw_value, DbImpactDimension, IMPACT_DIMENSION_FROM_DB)
    if group_by is ScoresGroupBy.quality_dimension:
        return _dimension_to_api(raw_value, DbQualityDimension, QUALITY_DIMENSION_FROM_DB)
    return str(raw_value)


def _dimension_to_api(raw_value, db_enum, from_db_map):
    """Best-effort DB → API mapping. Unrecognized values (should not happen in
    practice — DB values are constrained) fall back to lowercase of the raw."""
    try:
        return from_db_map[db_enum(raw_value)].value
    except (ValueError, KeyError):
        return str(raw_value).lower()
