import logging

from testgen.commands.queries.rollup_scores_query import RollupScoresSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.common.database.database_service import execute_db_queries

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
