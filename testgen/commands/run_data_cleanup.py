"""Per-project data retention cleanup.

Deletes profiling runs, test runs, and their child results older than the
project's retention period, plus aged-out staging, score history, and
job_execution records.

Always preserves the most recent profiling run per table group and the most
recent test run per test suite (including monitor suites). Profiling is
expensive and tends to run infrequently; downstream features — test
generation, freshness monitor generation, data catalog, and MCP analysis
tools — depend on the most recent profiling result for a table group, so
the project must always retain a baseline regardless of retention period
or run cadence.
"""

import logging
from datetime import UTC, datetime, timedelta

from testgen.common.models import database_session
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.scores import ScoreDefinitionResultHistoryEntry, ScoreHistoryLatestRun
from testgen.common.models.stg_data_chars_update import StgDataCharsUpdate
from testgen.common.models.stg_functional_table_update import StgFunctionalTableUpdate
from testgen.common.models.stg_test_definition_update import StgTestDefinitionUpdate
from testgen.common.models.test_run import TestRun

LOG = logging.getLogger("testgen")

BATCH_SIZE = 1000


def run_data_cleanup(project_code: str, retention_days: int) -> None:
    started_at = datetime.now(UTC)
    cutoff = started_at - timedelta(days=retention_days)
    LOG.info(
        "Data retention cleanup started: project=%s retention_days=%d cutoff=%s",
        project_code, retention_days, cutoff.isoformat(),
    )

    with database_session():
        protected_profiling_ids = ProfilingRun.find_latest_per_table_group(project_code)
        protected_test_run_ids = TestRun.find_latest_per_test_suite(project_code)
        # The run id is the job execution id, so the protected run ids are
        # already the job executions the sweep must carve out.
        protected_job_execution_ids = protected_profiling_ids | protected_test_run_ids

    LOG.info(
        "Protected latest runs: profiling=%d test=%d job_executions=%d",
        len(protected_profiling_ids), len(protected_test_run_ids), len(protected_job_execution_ids),
    )

    # Each delete owns its per-batch transactions internally — committing
    # between batches releases locks and bounds WAL growth for large sweeps.
    deleted_profiling = ProfilingRun.delete_older_than(
        cutoff=cutoff,
        project_code=project_code,
        protected_ids=protected_profiling_ids,
        batch_size=BATCH_SIZE,
    )

    deleted_tests = TestRun.delete_older_than(
        cutoff=cutoff,
        project_code=project_code,
        protected_ids=protected_test_run_ids,
        batch_size=BATCH_SIZE,
    )

    deleted_job_executions = JobExecution.delete_older_than(
        cutoff=cutoff,
        project_code=project_code,
        protected_ids=protected_job_execution_ids,
        batch_size=BATCH_SIZE,
    )

    # Score history: read protected mapping keys BEFORE deleting from either
    # table — we need score_history_latest_runs intact to compute the carve-out
    # for score_definition_results_history.
    with database_session():
        protected_history_keys = ScoreHistoryLatestRun.find_protected_keys(
            protected_profiling_ids=protected_profiling_ids,
            protected_test_run_ids=protected_test_run_ids,
        )

    deleted_score_history = ScoreDefinitionResultHistoryEntry.delete_older_than(
        cutoff=cutoff,
        project_code=project_code,
        protected_keys=protected_history_keys,
        batch_size=BATCH_SIZE,
    )

    deleted_score_latest = ScoreHistoryLatestRun.delete_older_than(
        cutoff=cutoff,
        project_code=project_code,
        protected_keys=protected_history_keys,
        batch_size=BATCH_SIZE,
    )

    # Staging tables: defensive cleanup of orphans left behind by failed jobs. Each run deletes
    # its own rows when it finishes, so anything still here past the cutoff belongs to a run that
    # never got that far. No carve-out: the cutoff is compared against the staged run_date, which
    # a backdated run can set far enough in the past to sweep its own rows mid-flight.
    with database_session():
        deleted_stg = (
            StgFunctionalTableUpdate.delete_older_than(cutoff, project_code)
            + StgDataCharsUpdate.delete_older_than(cutoff, project_code)
            + StgTestDefinitionUpdate.delete_older_than(cutoff, project_code)
        )

    elapsed = (datetime.now(UTC) - started_at).total_seconds()
    LOG.info(
        "Data retention cleanup complete: project=%s "
        "deleted_profiling=%d deleted_tests=%d deleted_job_executions=%d "
        "deleted_score_history=%d deleted_score_latest=%d deleted_staging=%d elapsed=%.1fs",
        project_code, deleted_profiling, deleted_tests, deleted_job_executions,
        deleted_score_history, deleted_score_latest, deleted_stg, elapsed,
    )
