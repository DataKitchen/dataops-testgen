"""Score rollup job: recalculates DQ scores after a profiling or test run completes.

Invoked via the scheduler (enqueued by a final callback on the parent run), or
called directly by callers without a running scheduler (quick-start, functional
tests). Identified by the parent JE id; `parent_job_key` selects the flavor.
"""

import logging
from uuid import UUID

from sqlalchemy import select

from testgen.commands.queries.rollup_scores_query import RollupScoresSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.common import execute_db_queries
from testgen.common.models import database_session
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite

LOG = logging.getLogger("testgen")


def run_score_update(parent_job_id: str, parent_job_key: str) -> None:
    """Roll up scores for the run linked to the given parent job execution."""
    parent_je_id = UUID(parent_job_id)
    match parent_job_key:
        case "run-profile":
            _rollup_profiling(parent_je_id)
        case "run-tests":
            _rollup_test(parent_je_id)
        case _:
            raise ValueError(f"run_score_update: unsupported parent_job_key {parent_job_key!r}")


def _rollup_profiling(parent_je_id: UUID) -> None:
    with database_session() as session:
        profiling_run = session.scalars(
            select(ProfilingRun).where(ProfilingRun.job_execution_id == parent_je_id)
        ).first()
        if not profiling_run:
            LOG.error("No profiling_run found for job execution %s; skipping score rollup", parent_je_id)
            return
        run_id = str(profiling_run.id)
        table_group_id = profiling_run.table_groups_id
        project_code = profiling_run.project_code
        refresh_date = profiling_run.profiling_starttime

    LOG.info("Rolling up profiling scores for job execution %s", parent_je_id)
    execute_db_queries(RollupScoresSQL(run_id, table_group_id).rollup_profiling_scores())
    run_refresh_score_cards_results(
        project_code=project_code,
        add_history_entry=True,
        refresh_date=refresh_date,
    )


def _rollup_test(parent_je_id: UUID) -> None:
    with database_session() as session:
        row = session.execute(
            select(TestRun.id, TestRun.test_starttime, TestSuite.table_groups_id, TestSuite.project_code)
            .join(TestSuite, TestRun.test_suite_id == TestSuite.id)
            .where(TestRun.job_execution_id == parent_je_id)
        ).first()
        if not row:
            LOG.error("No test_run found for job execution %s; skipping score rollup", parent_je_id)
            return
        run_id, refresh_date, table_group_id, project_code = row

    LOG.info("Rolling up test scores for job execution %s", parent_je_id)
    execute_db_queries(
        RollupScoresSQL(str(run_id), table_group_id).rollup_test_scores(update_prevalence=True, update_table_group=True),
    )
    run_refresh_score_cards_results(
        project_code=project_code,
        add_history_entry=True,
        refresh_date=refresh_date,
    )
