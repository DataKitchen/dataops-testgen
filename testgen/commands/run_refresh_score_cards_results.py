import logging

from testgen.common.models.scores import ScoreCard, ScoreDefinition, ScoreDefinitionResult

LOG = logging.getLogger("testgen")


def run_refresh_score_cards_results(project_code: str | None = None, definition_id: str | None = None):
    LOG.info("CurrentStep: Initializing scorecards results refresh")

    try:
        definitions = []
        if not definition_id:
            definitions = ScoreDefinition.all(project_code=project_code, fetch_filters=True, fetch_results=True)
        else:
            definitions.append(ScoreDefinition.get(definition_id))
    except Exception:
        LOG.exception("CurrentStep: Stopping scorecards results refresh after unexpected error")
        return

    for definition in definitions:
        LOG.info(
            "CurrentStep: Refreshing results for scorecard %s in project %s",
            definition.name,
            definition.project_code,
        )

        try:
            fresh_score_card = definition.as_score_card()
            definition.results = _score_card_to_results(fresh_score_card)
            definition.save()
            LOG.info(
                "CurrentStep: Done rereshing scorecard %s in project %s",
                definition.name,
                definition.project_code,
            )
        except Exception:
            LOG.exception(
                "CurrentStep: Unexpected error refreshing scorecard %sin project %s",
                definition.name,
                definition.project_code,
            )

    scope = "all scorecards"
    if project_code:
        scope = f"all scorecards in project {project_code}"
    if definition_id:
        scope = f"scorecard {definition_id}"
    LOG.info("CurrentStep: Refreshing results for %s is over", scope)


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
