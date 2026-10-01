import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from testgen.commands.queries.profiling_query import (
    HygieneIssueType,
    ProfilingSQL,
    TableSampling,
    calculate_sampling_params,
)
from testgen.commands.run_refresh_data_chars import run_data_chars_refresh
from testgen.common import (
    execute_db_queries,
    fetch_dict_from_db,
    set_target_db_params,
)
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import WorkerOutcome, get_flavor_service
from testgen.common.database.profiling_capabilities import ProfilingCapabilities, resolve_profiling_capabilities
from testgen.common.enums import JobKey, JobSource, JobStatus, run_duration_seconds
from testgen.common.job_context import job_context
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.data_table import DataTable
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import PROGRESS_KEYS, ProfilingRun, ProgressKey, ProgressStatus
from testgen.common.models.stg_functional_table_update import StgFunctionalTableUpdate
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.pausable_job import PausableJob, Step
from testgen.common.profile_frequency import build_frequent_values, with_frequent_patterns
from testgen.common.read_file import get_template_files

LOG = logging.getLogger("testgen")

# Bump when a change alters what a profiling pass records in profile_results -- new or dropped
# measures, or a different meaning for an existing one. A parked run resuming under a build that
# measures differently would file both readings under one profiling run; a bump discards its
# checkpoint so the run starts over and is measured one way.
PROFILE_RESULT_SHAPE_VERSION = 2


@with_database_session
def report_profiling_run(job_exec: JobExecution) -> None:
    """Send the ``run-profiling`` telemetry event for a run that has settled.

    Runs as a final callback so the duration is the one the run ended up with, which across a
    stop and continue is more than the handler that finished the work knows about.
    """
    if job_exec.status not in (JobStatus.COMPLETED, JobStatus.ERROR):
        # A cancel settles through these same callbacks, and the counts it would carry describe
        # work somebody abandoned rather than a run that produced results.
        return

    profiling_run = ProfilingRun.get(job_exec.id)
    if profiling_run is None:
        # A failure before the run row is written leaves nothing to report on.
        return

    # Settling releases the delete guard that held these in place, so either can be gone by
    # now. Report what is left rather than raising into a caller that swallows the event.
    table_group = TableGroup.get(profiling_run.table_groups_id)
    connection = Connection.get(profiling_run.connection_id)
    MixpanelService().send_event(
        "run-profiling",
        source=job_exec.source.upper(),
        username=job_exec.kwargs.get("username"),
        sql_flavor=connection.sql_flavor_code if connection else None,
        sampling=table_group.profile_use_sampling if table_group else None,
        table_count=profiling_run.table_ct or 0,
        column_count=profiling_run.column_ct or 0,
        run_duration=run_duration_seconds(job_exec.active_seconds, job_exec.status),
    )


@with_database_session
def run_profiling(
    table_group_id: str | UUID,
    username: str | None = None,
    run_date: datetime | None = None,
) -> UUID:
    if table_group_id is None:
        raise ValueError("Table Group ID was not specified")

    job = ProfilingJob(table_group_id, username=username, run_date=run_date)
    job.execute()
    return job.profiling_run.id


class ProfilingJob(PausableJob[ColumnChars]):
    """Profile every column of a table group, in steps that can stop and continue later.

    The steps, in order: refresh the data catalog, profile each column, run frequency
    analysis, detect hygiene issues, and queue test and monitor generation. Each step's work sits inside a
    checkpointed guard, so a pause stops the run at a work-key boundary and a later process
    continues from there. ``STEPS`` at the foot of the class binds these to their methods.
    """

    def __init__(
        self,
        table_group_id: str | UUID,
        username: str | None = None,
        run_date: datetime | None = None,
    ) -> None:
        job_id = job_context.get().job_id
        if job_id is None:
            raise ValueError("Profiling must run as a job, but no job context was set")

        super().__init__(job_id=job_id)
        self.table_group_id = table_group_id
        self.username = username
        self.time_delta = (run_date - datetime.now(UTC)) if run_date else timedelta()

        # Everything below is derived in on_start, which runs inside execute() -- so constructing
        # the job neither reads entities, writes a row, nor touches process-global target params.
        self.table_group: TableGroup | None = None
        self.connection: Connection | None = None
        self.profiling_run: ProfilingRun | None = None
        self.sql_generator: ProfilingSQL | None = None
        self.data_chars: list[ColumnChars] = []
        self.sampling_params: dict[str, TableSampling] = {}
        self.table_record_counts: dict[str, int] = {}
        self.capabilities = ProfilingCapabilities()

    def canonical_key(self, key: ColumnChars) -> str:
        return f"{key.schema_name}\x1f{key.table_name}\x1f{key.column_name}"

    def on_start(self) -> None:
        LOG.info(f"Starting profiling run for table group {self.table_group_id}")
        self.table_group = TableGroup.get(self.table_group_id)
        self.connection = Connection.get(self.table_group.connection_id)
        set_target_db_params(self.connection.__dict__, self.table_group)

        # Reuse the row when one is already there: a resumed run keeps its original start
        # time, which anchors the date-range measures, and the progress it already recorded.
        self.profiling_run = ProfilingRun.get(self.job_id)
        if self.profiling_run is None:
            self.profiling_run = ProfilingRun(
                id=self.job_id,
                project_code=self.table_group.project_code,
                connection_id=self.connection.connection_id,
                table_groups_id=self.table_group.id,
                profiling_starttime=datetime.now(UTC) + self.time_delta,
            )
        self.profiling_run.init_progress()
        self.profiling_run.save()
        get_current_session().commit()

        self.sql_generator = ProfilingSQL(self.connection, self.table_group, self.profiling_run)

        LOG.info(
            f"Profiling run: {self.profiling_run.id}, Table group: {self.table_group.table_groups_name}, "
            f"Connection: {self.connection.connection_name}"
        )

    def on_restart(self) -> None:
        # The world moved under the pause, so the results are a fresh run's, not the old one's.
        self.profiling_run.profiling_starttime = datetime.now(UTC) + self.time_delta

        # A run that starts over keeps its id, and the usual reason to start over is that a
        # column went away. Rewriting the columns that remain would leave the ones that do not
        # sitting in the results, counted and screened as though they were still there.
        if cleared := ProfileResult.delete_for_run(self.profiling_run.id):
            LOG.info(f"Cleared {cleared} result(s) written before the run started over")
        HygieneIssue.delete_for_run(self.profiling_run.id)
        # Staged under the run id too, and the table classification staged from the abandoned
        # attempt's results contradicts the one the restart stages from the columns that remain.
        StgFunctionalTableUpdate.delete_for_run(self.profiling_run.id)

        # The restart discards the abandoned attempt's results, so its recorded progress goes with
        # them; otherwise a step the restart re-runs cleanly would keep the earlier attempt's warning.
        self.profiling_run.progress = []
        self.profiling_run.init_progress()

        get_current_session().commit()

    # ---- progress ---------------------------------------------------------------------

    def on_step_start(self, step: Step) -> None:
        self._set_progress(step, "Running")

    def on_step_progress(self, step: Step, done: int, total: int) -> None:
        # fan_out commits right after this, so the progress write joins that commit instead of
        # adding a second one per work key.
        self._set_progress(step, "Running", detail=f"{done} of {total}", commit=False)

    def on_step_end(self, step: Step, errors: int) -> None:
        if errors:
            self._set_progress(
                step,
                "Warning",
                error=f"{errors} column{'s' if errors > 1 else ''} had errors. See details in results.",
            )
        else:
            # Columns an earlier process lost are still lost, and its account of them is the
            # only one there will be, so finishing the rest cleanly does not clear the warning.
            recorded = self.profiling_run.progress_error(step.name)
            self._set_progress(step, "Warning" if recorded else "Completed")

    def on_step_failed(self, step: Step, error: str) -> None:
        self._set_progress(step, "Warning", error=f"Error encountered. {error}")

    def _set_progress(
        self,
        step: Step,
        status: ProgressStatus,
        detail: str | None = None,
        error: str | None = None,
        commit: bool = True,
    ) -> None:
        # The display is coarser than the step list; steps without an entry stay silent.
        if step.name not in PROGRESS_KEYS:
            return
        self.profiling_run.set_progress(cast(ProgressKey, step.name), status, detail=detail, error=error)
        self.profiling_run.save()
        if commit:
            get_current_session().commit()

    # ---- steps ------------------------------------------------------------------------

    def _data_chars(self) -> None:
        """Take stock of what there is to profile, refreshing the catalog on a fresh run.

        A resumed run reads the catalog back instead: the counts it recorded are what the
        rest of the run was planned against, and re-reading the target would let a table
        that has grown since change how later columns are measured.
        """
        # Pinned before any work: neither the measures a pass records nor the queries that take
        # them show up in a work key, so a resume under a build that measures differently would
        # file both readings under one profiling run. A mismatch discards the checkpoint instead.
        self.pin("result_shape", PROFILE_RESULT_SHAPE_VERSION)
        self.pin("profiling_templates", _profiling_template_digest(self.sql_generator.flavor))
        # Resolved inside the step so an unreachable target fails this step like any other target
        # error. Pinned because the probe can answer differently once the target is upgraded, which
        # would file an exact and an approximate reading of the same measure under one run.
        self.capabilities = resolve_profiling_capabilities(self.sql_generator.flavor_service)
        self.pin("approx_percentile", self.capabilities.approx_percentile)

        if not self.once(self._refresh_catalog):
            LOG.info("Reading the data catalog recorded by the interrupted run")
            self.data_chars = DataTable.list_column_chars(self.table_group.id)

        if self.table_group.profile_exclude_xde:
            self.data_chars = _exclude_xde_columns(self.data_chars, self.table_group.id)

        distinct_tables = {(column.table_name, column.record_ct) for column in self.data_chars}
        self.profiling_run.table_ct = len(distinct_tables)
        self.profiling_run.column_ct = len(self.data_chars)
        self.profiling_run.record_ct = sum(table[1] for table in distinct_tables)
        self.profiling_run.data_point_ct = sum(column.record_ct for column in self.data_chars)

        if not self.data_chars:
            LOG.info("No columns were selected to profile.")
            return

        self.table_record_counts = {column.table_name: column.record_ct for column in self.data_chars}
        self.sampling_params = _compute_sampling_params(self.sql_generator, self.data_chars)

        # Sampling does not show up in a work key, so nothing else would notice it drifting while
        # the run is parked -- and a change would leave one run measured two ways.
        self.pin(
            "sampling",
            [
                bool(self.table_group.profile_use_sampling),
                self.table_group.profile_sample_percent,
                self.table_group.profile_sample_min_count,
            ],
        )
        # The record counts these settings are applied to also decide sample size and scaling, yet
        # a test run can refresh them mid-pause. Pin them too, or a resumed run samples some columns
        # at the old size and scales them by the new ratio. Coerced to int: a target COUNT can come
        # back as Decimal, which the checkpoint's JSON cannot serialize and would not compare equal.
        self.pin("record_counts", {table: int(count) for table, count in self.table_record_counts.items()})

    def _refresh_catalog(self) -> None:
        self.data_chars = run_data_chars_refresh(
            self.connection, self.table_group, self.profiling_run.profiling_starttime
        )

    def _col_profiling(self) -> None:
        if not self.data_chars:
            # An emptied catalog on resume means every task vanished, which has to restart the run
            # rather than complete over stale rows.
            self.no_work()
            return

        columns = _order_largest_work_first(self.data_chars, self.table_record_counts)
        LOG.info(f"Running column profiling queries: {len(columns)}")

        def handle(outcome: WorkerOutcome[ColumnChars, list[dict]]) -> None:
            if outcome.result:
                row = with_frequent_patterns(outcome.result[0])
                row.update(self.sql_generator.profiled_row_values(outcome.key, self.capabilities.approx_percentile))
                if table_sampling := self.sampling_params.get(outcome.key.table_name):
                    ProfileResult.scale_sampled_estimates(row, table_sampling.sample_ratio)
                ProfileResult.upsert(row)

        result = self.fan_out(
            columns,
            self._build_column_query,
            _fetch_target,
            handle,
            on_error=lambda column, error: _write_column_error(self.sql_generator, column, error),
            max_threads=self.connection.effective_max_threads,
        )

        if result.errors:
            LOG.warning(f"Errors running column profiling queries: {result.errors}")
        if result.all_failed:
            raise RuntimeError(f"{result.errors} errors during column profiling. See details in results.")

    def _build_column_query(self, column: ColumnChars) -> tuple[str, dict]:
        # Built here, not in the worker, so the ORM session is only touched on this thread.
        return self.sql_generator.run_column_profiling(
            column,
            self.sampling_params.get(column.table_name),
            use_approx_percentile=self.capabilities.approx_percentile,
        )

    def _freq_analysis(self) -> None:
        if not self.data_chars:
            return

        LOG.info("Selecting columns for frequency analysis")
        frequency_columns = [
            ColumnChars(**column)
            for column in fetch_dict_from_db(*self.sql_generator.get_frequency_analysis_columns())
        ]
        if not frequency_columns:
            # Losing every eligible column means the column pass's results are not the ones the
            # checkpoint was written against.
            self.no_work()
            return

        frequency_columns = _order_largest_work_first(frequency_columns, self.table_record_counts)
        LOG.info(f"Running frequency analysis queries: {len(frequency_columns)}")
        result = self.fan_out(
            frequency_columns,
            lambda column: self.sql_generator.run_frequency_analysis(
                column, self.sampling_params.get(column.table_name)
            ),
            _fetch_target,
            lambda outcome: _write_frequency_result(self.sql_generator, outcome.key, outcome.result)
            if outcome.result
            else None,
            on_error=lambda column, error: _write_frequency_error(self.sql_generator, column, error),
            max_threads=self.connection.effective_max_threads,
        )
        if result.errors:
            LOG.warning(f"Errors running frequency analysis queries: {result.errors}")

    def _hygiene_issues(self) -> None:
        if not self.data_chars:
            return
        self.once(self._detect_hygiene_issues)

    def _detect_hygiene_issues(self) -> None:
        LOG.info("Detecting functional data types and critical data elements")
        execute_db_queries(self.sql_generator.update_profiling_results())

        LOG.info("Retrieving hygiene issue types")
        hygiene_issue_types = [
            HygieneIssueType(**item) for item in fetch_dict_from_db(*self.sql_generator.get_hygiene_issue_types())
        ]

        # Detection inserts, so a step that restarts after being interrupted would double this
        # run's findings and the counts drawn from them.
        if removed := HygieneIssue.delete_for_run(self.profiling_run.id):
            LOG.info(f"Cleared {removed} hygiene issue(s) recorded before the run was interrupted")
        # Commit the delete before the queries below: they run on a separate connection and
        # would block indefinitely on the rows this DELETE locks, with nothing to break the wait.
        get_current_session().commit()

        LOG.info("Detecting hygiene issues and updating prevalence and counts")
        execute_db_queries(
            [
                *[
                    query
                    for issue_type in hygiene_issue_types
                    if (query := self.sql_generator.detect_hygiene_issue(issue_type))
                ],
                *[
                    self.sql_generator.update_hygiene_issue_prevalence(issue_type)
                    for issue_type in hygiene_issue_types
                    if issue_type.dq_score_prevalence_formula
                ],
                self.sql_generator.update_hygiene_issue_counts(),
            ]
        )

    def _generate_tests_step(self) -> None:
        self.once(self._enqueue_generation)

    def _enqueue_generation(self) -> None:
        """Queue the follow-up generation jobs rather than run them in this process.

        ``is_first_profile_run`` is read here, while it is still true: the score-update job that
        stamps ``last_complete_profile_run_id`` runs as a separate follow-up, so deciding what to
        generate at enqueue time -- and passing the monitor mode along -- keeps that decision from
        racing it.
        """
        is_first_profile_run = not self.table_group.last_complete_profile_run_id

        if self.table_group.monitor_test_suite_id:
            monitor_suite = TestSuite.get(self.table_group.monitor_test_suite_id)
            JobExecution.submit(
                job_key=JobKey.run_monitor_generation,
                kwargs={
                    "monitor_suite_id": str(self.table_group.monitor_test_suite_id),
                    # Only Freshness depends on profiling results.
                    "monitors": ["Freshness_Trend"],
                    # Insert for new tables only, if the user disabled regeneration.
                    "mode": "upsert" if is_first_profile_run or monitor_suite.monitor_regenerate_freshness else "insert",
                    "profile_run_id": str(self.profiling_run.id),
                },
                source=JobSource.system,
                project_code=self.table_group.project_code,
            )

        if is_first_profile_run and self.table_group.default_test_suite_id:
            JobExecution.submit(
                job_key=JobKey.run_test_generation,
                kwargs={
                    "test_suite_id": str(self.table_group.default_test_suite_id),
                    "profile_run_id": str(self.profiling_run.id),
                },
                source=JobSource.system,
                project_code=self.table_group.project_code,
            )

    STEPS = (
        Step("data_chars", _data_chars),
        Step("col_profiling", _col_profiling),
        Step("freq_analysis", _freq_analysis, fatal=False),
        Step("hygiene_issues", _hygiene_issues, fatal=False),
        Step("generate_tests", _generate_tests_step, fatal=False),
    )


def _exclude_xde_columns(data_chars: list[ColumnChars], table_group_id: UUID) -> list[ColumnChars]:
    """Filter out columns marked as excluded_data_element in data_column_chars."""
    xde_columns = DataColumnChars.select_where(
        DataColumnChars.table_groups_id == table_group_id,
        DataColumnChars.excluded_data_element.is_(True),
    )
    if not xde_columns:
        return data_chars

    excluded = {(col.table_name, col.column_name) for col in xde_columns}
    filtered = [col for col in data_chars if (col.table_name, col.column_name) not in excluded]
    if len(filtered) < len(data_chars):
        LOG.info(f"Excluding {len(data_chars) - len(filtered)} XDE columns from profiling")
    return filtered


def _profiling_template_digest(sql_flavor: str) -> str:
    """Digest of the templates that measure a column for the given flavor."""
    digest = hashlib.sha256()
    entries = get_template_files(r".*", sub_directory=f"flavors/{sql_flavor}/profiling")
    for entry in sorted(entries, key=lambda file: file.name):
        digest.update(entry.name.encode("utf-8"))
        digest.update(entry.read_text(encoding="utf-8").encode("utf-8"))
    return digest.hexdigest()


def _compute_sampling_params(
    sql_generator: ProfilingSQL, data_chars: list[ColumnChars]
) -> dict[str, TableSampling]:
    table_group = sql_generator.table_group
    sampling_params: dict[str, TableSampling] = {}
    if not table_group.profile_use_sampling:
        return sampling_params

    sampleable_types = get_flavor_service(sql_generator.flavor).sampleable_object_types(
        sql_generator.connection.sql_flavor_code
    )
    # Empty set = flavor opts out of sampling; skip so exact counts aren't
    # scaled by a sample ratio that never applied.
    if sampleable_types == frozenset():
        return sampling_params
    for column in data_chars:
        if sampling_params.get(column.table_name):
            continue
        if sampleable_types is not None and column.object_type not in sampleable_types:
            continue
        result = calculate_sampling_params(
            table_name=column.table_name,
            record_count=column.record_ct,
            sample_percent_raw=table_group.profile_sample_percent,
            min_sample=table_group.profile_sample_min_count,
        )
        if result:
            sampling_params[column.table_name] = result
    return sampling_params


def _order_largest_work_first(
    columns: list[ColumnChars], table_record_counts: dict[str, int]
) -> list[ColumnChars]:
    """Order work keys deterministically, largest table first.

    Ordering does not affect results; largest tables first helps the threads to finish about
    the same time. The name components break ties, since the queries these columns come from
    do not all order their rows and a resume compares its task list against the stored one.
    """
    return sorted(
        columns,
        key=lambda column: (
            -table_record_counts.get(column.table_name, 0),
            column.schema_name,
            column.table_name,
            column.column_name,
        ),
    )


def _write_column_error(sql_generator: ProfilingSQL, column: ColumnChars, error: str) -> None:
    ProfileResult.upsert(sql_generator.column_error_row(column, error))


def _fetch_target(built: tuple[str, dict]) -> list[dict]:
    return fetch_dict_from_db(*built, use_target_db=True)


def _write_frequency_error(sql_generator: ProfilingSQL, column: ColumnChars, error: str) -> None:
    # Only the error: the column pass measured this column and its row holds those measures, so
    # writing the wider error-row shape here would overwrite them with the nulls this step knows.
    ProfileResult.upsert(
        {
            "table_groups_id": sql_generator.table_group.id,
            "table_name": column.table_name,
            "column_name": column.column_name,
            "profile_run_id": sql_generator.profiling_run.id,
            "query_error": error[: sql_generator.max_error_length],
        }
    )


def _write_frequency_result(sql_generator: ProfilingSQL, column: ColumnChars, rows: list[dict]) -> None:
    # Identity comes from the column read out of profile_results (so it matches the stored
    # row exactly); only the frequency measures are overwritten on conflict.
    ProfileResult.upsert(
        {
            "table_groups_id": sql_generator.table_group.id,
            "table_name": column.table_name,
            "column_name": column.column_name,
            "profile_run_id": sql_generator.profiling_run.id,
            "frequent_values": build_frequent_values(rows),
            "distinct_value_hash": rows[0]["distinct_value_hash"],
        }
    )
