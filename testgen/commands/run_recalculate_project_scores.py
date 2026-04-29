"""Recalculate all DQ scores for a project.

Used when the use_dq_score_weights toggle changes so that existing rollup
results reflect the new weighting configuration without requiring new runs.
"""
import logging

from sqlalchemy import select

from testgen.commands.queries.rollup_scores_query import RollupScoresSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.common import execute_db_queries
from testgen.common.models import database_session
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

LOG = logging.getLogger("testgen")


def run_recalculate_project_scores(project_code: str) -> None:
    with database_session() as session:
        table_groups = session.scalars(
            select(TableGroup).where(TableGroup.project_code == project_code)
        ).all()

    for tg in table_groups:
        tg_id = str(tg.id)

        if tg.last_complete_profile_run_id:
            LOG.info("Recalculating profiling scores for table group %s", tg_id)
            execute_db_queries(
                RollupScoresSQL(str(tg.last_complete_profile_run_id), tg_id).rollup_profiling_scores()
            )

        with database_session() as session:
            test_suites = session.scalars(
                select(TestSuite).where(
                    TestSuite.table_groups_id == tg.id,
                    TestSuite.last_complete_test_run_id != None,
                )
            ).all()

        for i, ts in enumerate(test_suites):
            LOG.info("Recalculating test scores for test suite %s in table group %s", ts.id, tg_id)
            execute_db_queries(
                RollupScoresSQL(str(ts.last_complete_test_run_id), tg_id).rollup_test_scores(
                    update_table_group=(i == len(test_suites) - 1),
                )
            )

    run_refresh_score_cards_results(project_code=project_code)
