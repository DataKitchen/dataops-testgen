import datetime
import logging
import time

from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.scores import (
    SCORE_CATEGORIES,
    ScoreCard,
    ScoreDefinition,
    ScoreDefinitionBreakdownItem,
    ScoreDefinitionResult,
    ScoreDefinitionResultHistoryEntry,
)

LOG = logging.getLogger("testgen")


@with_database_session
def run_refresh_score_cards_results(
    project_code: str | None = None,
    definition_id: str | None = None,
    add_history_entry: bool = False,
    refresh_date: datetime.datetime | None = None,
):
    start_time = time.time()
    _refresh_date = refresh_date or datetime.datetime.now(datetime.UTC)
    LOG.info("CurrentStep: Initializing scorecards results refresh")

    try:
        definitions = []
        if not definition_id:
            definitions = ScoreDefinition.all(project_code=project_code)
        else:
            definitions.append(ScoreDefinition.get(str(definition_id)))
    except Exception:
        LOG.exception("CurrentStep: Stopping scorecards results refresh after unexpected error")
        return

    db_session = get_current_session()
    for definition in definitions:
        LOG.info(
            "CurrentStep: Refreshing results for scorecard %s in project %s",
            definition.name,
            definition.project_code,
        )

        try:
            fresh_score_card = definition.as_score_card()
            definition.results = []
            definition.breakdown = []
            db_session.flush([definition])

            definition.results = _score_card_to_results(fresh_score_card)
            definition.breakdown = _score_definition_to_results_breakdown(definition)
            if add_history_entry:
                LOG.info(
                    "CurrentStep: Adding history entry for scorecard %s in project %s",
                    definition.name,
                    definition.project_code,
                )

                historical_categories = ["score", "cde_score"]
                for result in definition.results:
                    if result.category in historical_categories:
                        history_entry = ScoreDefinitionResultHistoryEntry(
                            definition_id=result.definition_id,
                            category=result.category,
                            score=result.score,
                            last_run_time=_refresh_date,
                        )
                        definition.history.append(history_entry)
                        history_entry.add_as_cutoff()
            definition.save()
            LOG.info(
                "CurrentStep: Done rereshing scorecard %s in project %s",
                definition.name,
                definition.project_code,
            )
        except Exception:
            LOG.exception(
                "CurrentStep: Unexpected error refreshing scorecard %s in project %s",
                definition.name,
                definition.project_code,
            )

    scope = "all scorecards"
    if project_code:
        scope = f"all scorecards in project {project_code}"
    if definition_id:
        scope = f"scorecard {definition_id}"

    end_time = time.time()
    LOG.info("CurrentStep: Refreshing results for %s is over after %s seconds", scope, round(end_time - start_time, 2))


def _score_card_to_results(score_card: ScoreCard) -> list[ScoreDefinitionResult]:
    return [
        ScoreDefinitionResult(
            definition_id=score_card["id"],
            category="score",
            score=score_card["score"],
        ),
        ScoreDefinitionResult(
            definition_id=score_card["id"],
            category="cde_score",
            score=score_card["cde_score"],
        ),
        ScoreDefinitionResult(
            definition_id=score_card["id"],
            category="profiling_score",
            score=score_card["profiling_score"],
        ),
        ScoreDefinitionResult(
            definition_id=score_card["id"],
            category="testing_score",
            score=score_card["testing_score"],
        ),
        *[
            ScoreDefinitionResult(
                definition_id=score_card["id"],
                category=category["label"],
                score=category["score"],
            )
            for category in score_card.get("categories", [])
        ]
    ]


def _score_definition_to_results_breakdown(score_definition: ScoreDefinition) -> list[ScoreDefinitionBreakdownItem]:
    score_types = ["score", "cde_score"]
    categories = SCORE_CATEGORIES

    all_breakdown_items = []
    for category in categories:
        for score_type in score_types:
            breakdown = score_definition.get_score_card_breakdown(group_by=category, score_type=score_type)
            all_breakdown_items.extend([
                ScoreDefinitionBreakdownItem(
                    definition_id=score_definition.id,
                    category=category,
                    score_type=score_type,
                    **item,
                ) for item in breakdown
            ])

    return all_breakdown_items


@with_database_session
def run_recalculate_score_card(*, project_code: str, definition_id: str):
    LOG.info("Recalculating history for scorecard %s in project %s", definition_id, project_code)
    start_time = time.time()

    try:
        definition = ScoreDefinition.get(str(definition_id))
        definition.recalculate_scores_history()
        definition.save()
    except Exception:
        LOG.exception("CurrentStep: Stopping history recalculation after unexpected error")
        return

    end_time = time.time()
    LOG.info(
        "Recalculating history for scorecard %s in project %s is over after %s seconds",
        definition_id,
        project_code,
        round(end_time - start_time, 2),
    )
