import logging

from testgen.commands.queries.rollup_scores_query import RollupScoresSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.common.database.database_service import execute_db_queries
from testgen.common.enums import JobKey

LOG = logging.getLogger("testgen")


def run_profile_rollup_scoring_queries(project_code: str, run_id: str, table_group_id: str | None = None):
    sql_generator = RollupScoresSQL(run_id, table_group_id)
    execute_db_queries(sql_generator.rollup_profiling_scores())
    run_refresh_score_cards_results(project_code=project_code)


def run_test_rollup_scoring_queries(project_code: str, run_id: str, table_group_id: str | None = None):
    sql_generator = RollupScoresSQL(run_id, table_group_id)
    execute_db_queries(
        sql_generator.rollup_test_scores(update_table_group=table_group_id is not None)
    )
    run_refresh_score_cards_results(project_code=project_code)


def run_refresh_run_scores(run_job_key: JobKey, project_code: str, run_id: str, table_group_id: str | None = None) -> None:
    """Roll up a run's scores and refresh the project's scorecards, without adding a history entry.

    :param run_job_key: ``run-profile`` for a profiling run, ``run-tests`` for a test run.
    :param project_code: Project whose scorecards are refreshed.
    :param run_id: Run whose scores are rolled up.
    :param table_group_id: Table group to roll the scores up to; ``None`` when the run is not its latest.
    """
    match run_job_key:
        case JobKey.run_profile:
            run_profile_rollup_scoring_queries(project_code, run_id, table_group_id)
        case JobKey.run_tests:
            run_test_rollup_scoring_queries(project_code, run_id, table_group_id)
        case _:
            raise ValueError(f"Unsupported run_job_key {run_job_key!r}")
