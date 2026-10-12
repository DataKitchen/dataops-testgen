"""Score rollup after a profiling or test run completes.

A completed run's own score is rolled up in the run's process by ``rollup_run_and_request_refresh``,
which then requests a project score refresh. The refresh, run by the scheduler as one
``refresh-project-scores`` job per project at a time, rolls the scores up to the table groups and
refreshes the scorecards that can include them. ``run_score_update`` does both steps inline, without
the scheduler.
"""

import datetime
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from testgen.commands.queries.rollup_scores_query import RollupScoresSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.commands.run_rollup_scores import execute_rollup_queries
from testgen.common.enums import JobKey
from testgen.common.models import database_session, get_current_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite

LOG = logging.getLogger("testgen")


@dataclass(frozen=True)
class _RolledUpRun:
    project_code: str
    table_group_id: str
    run_date: datetime.datetime | None


def rollup_run_and_request_refresh(parent_job_id: str, parent_job_key: str) -> None:
    """Roll up the scores of the run linked to the given job execution, then request a project score refresh."""
    with database_session():
        run = _rollup_run(UUID(parent_job_id), parent_job_key)
        if run:
            JobExecution.request_project_score_refresh(
                run.project_code,
                profile_table_group_ids=[run.table_group_id] if parent_job_key == JobKey.run_profile else [],
                test_table_group_ids=[run.table_group_id] if parent_job_key == JobKey.run_tests else [],
                refresh_date=run.run_date,
            )


def run_project_score_refresh(
    project_code: str,
    profile_table_group_ids: list[str],
    test_table_group_ids: list[str],
    refresh_date: str | None,
) -> None:
    """Roll up the table groups' scores, then refresh the project's scorecards that can include them.

    :param project_code: Project whose scorecards are refreshed.
    :param profile_table_group_ids: Table groups whose profiling scores are rolled up.
    :param test_table_group_ids: Table groups whose test scores are rolled up.
    :param refresh_date: ISO date of the history entry added to each refreshed scorecard.
    """
    _rollup_table_groups(profile_table_group_ids, test_table_group_ids)
    run_refresh_score_cards_results(
        project_code=project_code,
        add_history_entry=True,
        refresh_date=datetime.datetime.fromisoformat(refresh_date) if refresh_date else None,
        table_group_ids={*profile_table_group_ids, *test_table_group_ids},
    )


def run_score_update(parent_job_id: str, parent_job_key: str) -> None:
    """Roll up the scores of the run linked to the given job execution and refresh its scorecards inline."""
    with database_session():
        run = _rollup_run(UUID(parent_job_id), parent_job_key)
        if run:
            run_project_score_refresh(
                run.project_code,
                profile_table_group_ids=[run.table_group_id] if parent_job_key == JobKey.run_profile else [],
                test_table_group_ids=[run.table_group_id] if parent_job_key == JobKey.run_tests else [],
                refresh_date=run.run_date.isoformat() if run.run_date else None,
            )


def _rollup_run(parent_je_id: UUID, parent_job_key: str) -> _RolledUpRun | None:
    match parent_job_key:
        case JobKey.run_profile:
            return _rollup_profiling_run(parent_je_id)
        case JobKey.run_tests:
            return _rollup_test_run(parent_je_id)
        case _:
            raise ValueError(f"Unsupported parent_job_key {parent_job_key!r}")


def _rollup_profiling_run(parent_je_id: UUID) -> _RolledUpRun | None:
    profiling_run = get_current_session().scalars(
        select(ProfilingRun).where(ProfilingRun.id == parent_je_id)
    ).first()
    if not profiling_run:
        LOG.error("No profiling_run found for job execution %s; skipping score rollup", parent_je_id)
        return None
    run = _RolledUpRun(
        project_code=profiling_run.project_code,
        table_group_id=str(profiling_run.table_groups_id),
        run_date=profiling_run.profiling_starttime,
    )

    LOG.info("Rolling up profiling run scores for job execution %s", parent_je_id)
    execute_rollup_queries(RollupScoresSQL(str(parent_je_id)).rollup_profiling_scores())
    return run


def _rollup_test_run(parent_je_id: UUID) -> _RolledUpRun | None:
    row = get_current_session().execute(
        select(TestRun.test_starttime, TestSuite.table_groups_id, TestSuite.project_code)
        .join(TestSuite, TestRun.test_suite_id == TestSuite.id)
        .where(TestRun.id == parent_je_id)
    ).first()
    if not row:
        LOG.error("No test_run found for job execution %s; skipping score rollup", parent_je_id)
        return None
    run = _RolledUpRun(project_code=row.project_code, table_group_id=str(row.table_groups_id), run_date=row.test_starttime)

    LOG.info("Rolling up test run scores for job execution %s", parent_je_id)
    execute_rollup_queries(RollupScoresSQL(str(parent_je_id)).rollup_test_scores(update_prevalence=True))
    return run


def _rollup_table_groups(profile_table_group_ids: list[str], test_table_group_ids: list[str]) -> None:
    for table_group_id in profile_table_group_ids:
        LOG.info("Rolling up profiling scores for table group %s", table_group_id)
        execute_rollup_queries(RollupScoresSQL(None, table_group_id).rollup_profiling_table_group())
    for table_group_id in test_table_group_ids:
        LOG.info("Rolling up test scores for table group %s", table_group_id)
        execute_rollup_queries(RollupScoresSQL(None, table_group_id).rollup_test_table_group())
