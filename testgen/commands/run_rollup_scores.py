import logging

from testgen.commands.queries.rollup_scores_query import CRollupScoresSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.common.database.database_service import execute_db_queries

LOG = logging.getLogger("testgen")


def run_profile_rollup_scoring_queries(project_code: str, run_id: str, table_group_id: str | None = None):
    LOG.info("CurrentStep: Initializing Profiling Scores Rollup")
    sql_generator = CRollupScoresSQL(run_id, table_group_id)

    queries = [sql_generator.GetRollupScoresProfileRunQuery()]
    if table_group_id: 
        queries.append(sql_generator.GetRollupScoresProfileTableGroupQuery())

    LOG.info("CurrentStep: Rolling up profiling scores")
    execute_db_queries(queries)
    run_refresh_score_cards_results(project_code=project_code)


def run_test_rollup_scoring_queries(project_code: str, run_id: str, table_group_id: str | None = None):
    LOG.info("CurrentStep: Initializing Testing Scores Rollup")
    sql_generator = CRollupScoresSQL(run_id, table_group_id)

    queries = [sql_generator.GetRollupScoresTestRunQuery()]
    if table_group_id: 
        queries.append(sql_generator.GetRollupScoresTestTableGroupQuery())

    LOG.info("CurrentStep: Rolling up testing scores")
    execute_db_queries(queries)
    run_refresh_score_cards_results(project_code=project_code)
