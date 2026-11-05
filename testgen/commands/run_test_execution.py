import logging
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select

from testgen.commands.queries.execute_tests_query import TestExecutionDef, TestExecutionSQL
from testgen.commands.test_generation import run_monitor_generation
from testgen.commands.test_thresholds_prediction import TestThresholdsPrediction
from testgen.common import (
    execute_db_queries,
    fetch_dict_from_db,
    set_target_db_params,
    write_to_app_db,
)
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import ThreadedProgress
from testgen.common.enums import JobKey, SuiteType, run_duration_seconds
from testgen.common.job_context import job_context, measurements_for, record_measurement
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.job_execution import RESTARTED_MESSAGE, JobExecution
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.common.stoppable_job import JobSignal, Step, StoppableJob

from .run_refresh_data_chars import run_data_chars_refresh
from .run_test_validation import ColumnLookup, run_test_validation

LOG = logging.getLogger("testgen")


def attach_column_chars(test_defs: list[TestExecutionDef], data_chars: list[ColumnChars], quote_char: str) -> None:
    """Set each test's catalog column, column type and key column, matched by exact name, else by
    case-insensitive name when only one column of the table has it.

    Args:
        test_defs: The tests to run.
        data_chars: The table group's catalog columns.
        quote_char: The flavor's identifier quote, stripped from the tests' column names.
    """
    columns = ColumnLookup(data_chars)
    for td in test_defs:
        td.column_chars = (
            columns.find(td.schema_name, td.table_name, td.column_name.strip(f" {quote_char}")) if td.column_name else None
        )
        td.column_type = td.column_chars.column_type if td.column_chars else None
        if td.groupby_names:
            td.key_column_chars = columns.find(td.schema_name, td.table_name, td.groupby_names.strip(f" {quote_char}"))


def retarget_match_schema(test_defs: list[TestExecutionDef], match_schema_name: str) -> None:
    """Point loaded referential tests at ``match_schema_name`` for this run.

    A referential test compares against a table outside its own table group, so where that table
    lives is not a property of the table group and does not move with it. A run whose reference
    data landed somewhere else carries the schema it landed in.

    A definition with no match schema stays without one: it has no referential target, and
    inventing one would turn a test validation reports as incomplete into a silent comparison.

    The stored ``test_definitions`` rows are untouched.
    """
    for test_def in test_defs:
        if test_def.match_schema_name:
            test_def.match_schema_name = match_schema_name


def _a_later_contract_run_is_latest(test_suite: TestSuite, test_run: TestRun) -> bool:
    """Whether the latest run of a contract started after ``test_run``."""
    if test_suite.suite_type != SuiteType.CONTRACT or not test_suite.last_complete_test_run_id:
        return False
    latest_start = get_current_session().scalar(
        select(TestRun.test_starttime).where(TestRun.id == test_suite.last_complete_test_run_id)
    )
    return latest_start is not None and latest_start > test_run.test_starttime


@with_database_session
def run_test_execution(
    test_suite_id: str | UUID,
    run_date: datetime | None = None,
    version_id: str | UUID | None = None,
    match_schema_name: str | None = None,
) -> UUID:
    if test_suite_id is None:
        raise ValueError("Test Suite ID was not specified")

    job = TestExecutionJob(test_suite_id, run_date=run_date, version_id=version_id, match_schema_name=match_schema_name)
    job.execute()
    return job.test_run.id


class TestExecutionJob(StoppableJob[int]):
    """Run a test suite's active tests against its table group, in steps that stop when asked to.

    The steps, in order: refresh the data catalog, prepare the tests (monitor definitions,
    thresholds, validation), run the QUERY, CAT, and METADATA tests, and roll up the results.
    """

    def __init__(
        self,
        test_suite_id: str | UUID,
        run_date: datetime | None = None,
        version_id: str | UUID | None = None,
        match_schema_name: str | None = None,
    ) -> None:
        super().__init__(job_context.get().job_id)
        self.test_suite_id = test_suite_id
        self.run_date = run_date
        self.version_id = version_id
        self.match_schema_name = match_schema_name
        self.test_run: TestRun | None = None
        self.writes_definitions = False
        self.data_chars: list[ColumnChars] = []
        self.valid_test_defs: list[TestExecutionDef] = []
        self._started = False

    def on_start(self) -> None:
        LOG.info(f"Starting test run for test suite {self.test_suite_id}")
        time_delta = (self.run_date - datetime.now(UTC)) if self.run_date else timedelta()

        LOG.info("Retrieving connection, table group, and test suite parameters")
        self.test_suite = TestSuite.get(self.test_suite_id)
        self.table_group = TableGroup.get(self.test_suite.table_groups_id)
        self.connection = Connection.get(self.table_group.connection_id)
        set_target_db_params(self.connection.__dict__, self.table_group)

        resolved_version_id = (
            UUID(str(self.version_id))
            if self.version_id
            else get_current_session().scalar(select(SuiteVersion.for_run(self.test_suite_id)))
        )
        LOG.info("Creating test run record")
        self.test_run = TestRun(
            id=self.job_id,
            test_suite_id=self.test_suite_id,
            test_starttime=datetime.now(UTC) + time_delta,
            version_id=resolved_version_id,
        )

        # This runs in a subprocess — commit after every save so progress is visible
        # to the UI (separate session) and to execute_db_queries (independent connection).
        self.test_run.init_progress()
        self.test_run.set_progress("data_chars", "Running")
        self.test_run.save()
        get_current_session().commit()

        # Both writeback steps narrow by the run's version, which for a contract is the frozen
        # agreement. Running an agreement does not rewrite it, or the terms in force stop being the
        # terms that were frozen and the version stops being reproducible. Decided here because
        # the prediction reads it after a run that fails at its first step.
        self.writes_definitions = not SuiteVersion.is_frozen_agreement(self.test_run.version_id)
        self._started = True
        LOG.info(
            f"Test run: {self.test_run.id}, Test suite: {self.test_suite.test_suite}, "
            f"Table group: {self.table_group.table_groups_name}, Connection: {self.connection.connection_name}"
        )

    def execute(self) -> None:
        stopped = False
        try:
            super().execute()
        except JobSignal:
            # A stopped run is abandoned: its results are incomplete, so they train nothing.
            stopped = True
            raise
        finally:
            if self._started and not stopped:
                self._predict_thresholds()

    def on_end(self) -> None:
        if self.test_run.checked_version_in_force() and not _a_later_contract_run_is_latest(self.test_suite, self.test_run):
            LOG.info("Updating latest run for test suite")
            self.test_suite.last_complete_test_run_id = self.test_run.id
            self.test_suite.save()
            get_current_session().commit()

    def _predict_thresholds(self) -> None:
        prediction_start = time.monotonic()
        try:
            if self.writes_definitions:
                TestThresholdsPrediction(self.test_suite, self.test_run).run()
        except Exception:
            LOG.exception("Error predicting test thresholds")
        record_measurement("prediction_duration", time.monotonic() - prediction_start)

    # ---- steps ----------------------------------------------------------------------------

    def _refresh_data_chars(self) -> None:
        self.data_chars = run_data_chars_refresh(self, self.connection, self.table_group, self.test_run.test_starttime)
        self.test_run.set_progress("data_chars", "Completed")

    def _prepare_tests(self) -> None:
        self.sql_generator = TestExecutionSQL(self.connection, self.table_group, self.test_suite, self.test_run)

        if self.test_suite.suite_type == SuiteType.MONITOR:
            _sync_monitor_definitions(self.sql_generator, self.data_chars)
            self.stop_if_requested()

        if self.writes_definitions:
            # Update the thresholds before retrieving the test definitions in the next steps
            LOG.info("Updating test thresholds based on history calculations")
            execute_db_queries([self.sql_generator.update_history_calc_thresholds()])
            self.stop_if_requested()

        LOG.info("Retrieving active test definitions in test suite")
        test_defs = fetch_dict_from_db(*self.sql_generator.get_active_test_definitions())
        test_defs = [TestExecutionDef(**item) for item in test_defs]

        if self.match_schema_name:
            retarget_match_schema(test_defs, self.match_schema_name)

        if not test_defs:
            LOG.info("No active tests to run")
            return

        LOG.info(f"Active test definitions: {len(test_defs)}")
        self.test_run.set_progress("validation", "Running")
        self.test_run.save()
        get_current_session().commit()
        self.stop_if_requested()

        self.valid_test_defs = run_test_validation(
            self.sql_generator,
            test_defs,
            self.data_chars,
            # A failure against a caller-supplied match schema says nothing about the stored definition.
            deactivate_invalid=self.test_suite.deactivates_invalid_tests and not self.match_schema_name,
        )
        invalid_count = len(test_defs) - len(self.valid_test_defs)
        self.test_run.set_progress(
            "validation",
            "Warning" if invalid_count else "Completed",
            error=f"{invalid_count} test{'s' if invalid_count > 1 else ''} had errors. See details in results." if invalid_count else None,
        )

        if self.valid_test_defs:
            attach_column_chars(self.valid_test_defs, self.data_chars, self.sql_generator.flavor_service.quote_character)
        else:
            LOG.info("No valid tests to run")

    def _run_run_type(self, run_type: Literal["QUERY", "CAT", "METADATA"]) -> None:
        if not self.valid_test_defs:
            return
        if not (run_test_defs := [td for td in self.valid_test_defs if td.run_type == run_type]):
            self.test_run.set_progress(run_type, "Completed")
            LOG.info(f"No {run_type} tests to run")
            return
        save_progress = self.test_suite.suite_type != SuiteType.MONITOR
        if run_type == "CAT":
            _run_cat_tests(self, self.sql_generator, run_test_defs, save_progress=save_progress)
        else:
            _run_tests(self, self.sql_generator, run_type, run_test_defs, save_progress=save_progress)

    def _query_step(self) -> None:
        self._run_run_type("QUERY")

    def _cat_step(self) -> None:
        self._run_run_type("CAT")

    def _metadata_step(self) -> None:
        self._run_run_type("METADATA")

    def _update_results(self) -> None:
        LOG.info("Updating test results and test run")
        self.test_run.save()
        get_current_session().commit()
        execute_db_queries(self.sql_generator.update_test_results())
        # Refresh needed because previous query updates the test run too
        self.test_run.refresh()

    # Run order: QUERY → CAT → METADATA is load-bearing for monitor suites.
    # Freshness_Trend (QUERY) writes the table fingerprint to test_results, which
    # Volume_Trend and Metric_Trend (both CAT) read at execution time to apply
    # freshness-gated thresholds (see TestExecutionSQL._get_params). Metadata tests
    # stay last so results for other tests are available to them. Do not reorder
    # without revisiting freshness-gating in the SQL templates and exec params.
    STEPS = (
        Step("data_chars", _refresh_data_chars),
        Step("prepare", _prepare_tests),
        Step("QUERY", _query_step),
        Step("CAT", _cat_step),
        Step("METADATA", _metadata_step),
        Step("results", _update_results),
    )


@with_database_session
def report_test_run(job_exec: JobExecution) -> None:
    """Send the ``run-tests`` or ``run-monitors`` telemetry event for a run that has settled."""
    test_run = TestRun.get(job_exec.id)
    if test_run is None:
        # A failure before the run row is written leaves nothing to report on.
        return

    # Settling releases the delete guard that held these in place, so any of them can be gone by
    # now. Report what is left rather than raising into a caller that swallows the event.
    test_suite = TestSuite.get(test_run.test_suite_id)
    table_group = TableGroup.get(test_suite.table_groups_id) if test_suite else None
    connection = Connection.get(table_group.connection_id) if table_group else None
    properties = {
        "source": job_exec.source.upper(),
        "sql_flavor": connection.sql_flavor_code if connection else None,
        "test_count": test_run.test_ct,
        "status": job_exec.status,
        **measurements_for(job_exec.id),
    }
    # A run a restart ended was active until the restart, so its total includes the downtime.
    if job_exec.error_message != RESTARTED_MESSAGE:
        properties["run_duration"] = run_duration_seconds(job_exec.active_seconds, job_exec.status)
    event = "run-monitors" if job_exec.job_key == JobKey.run_monitors else "run-tests"
    MixpanelService().send_event(event, **properties)


def _sync_monitor_definitions(sql_generator: TestExecutionSQL, data_chars: list[ColumnChars]) -> None:
    test_suite_id = sql_generator.test_run.test_suite_id

    schema_changes = fetch_dict_from_db(*sql_generator.has_schema_changes())[0]
    if schema_changes["has_table_drops"]:
        run_monitor_generation(test_suite_id, ["Freshness_Trend", "Volume_Trend", "Metric_Trend"], mode="delete")
    if schema_changes["has_table_adds"]:
        # Freshness monitors will be inserted after profiling
        run_monitor_generation(test_suite_id, ["Volume_Trend"], mode="insert")

    # Autogenerate missing freshness monitors if profiling data exists
    if sql_generator.table_group.last_complete_profile_run_id:
        missing_monitors = fetch_dict_from_db(*sql_generator.get_missing_freshness_monitors())
        if missing_monitors:
            table_names = [row["table_name"] for row in missing_monitors]
            run_monitor_generation(test_suite_id, ["Freshness_Trend"], mode="insert", table_names=table_names)

    # Regenerate monitors that errored in previous run or fail validation
    regen_tables_by_type: dict[str, set[str]] = defaultdict(set)

    errored_monitors = fetch_dict_from_db(*sql_generator.get_errored_autogen_monitors())
    for row in errored_monitors:
        regen_tables_by_type[row["test_type"]].add(row["table_name"])

    active_defs = [TestExecutionDef(**item) for item in fetch_dict_from_db(*sql_generator.get_active_test_definitions())]
    if active_defs:
        run_test_validation(sql_generator, active_defs, data_chars, defer_persistence=True)
        for td in active_defs:
            if td.errors and td.test_type in ("Freshness_Trend", "Volume_Trend") and td.lock_refresh != "Y":
                regen_tables_by_type[td.test_type].add(td.table_name)

    for test_type, table_names in regen_tables_by_type.items():
        run_monitor_generation(test_suite_id, [test_type], mode="upsert", table_names=list(table_names))


def _run_tests(
    job: StoppableJob,
    sql_generator: TestExecutionSQL,
    run_type: Literal["QUERY", "METADATA"],
    test_defs: list[TestExecutionDef],
    save_progress: bool = False,
) -> None:
    test_run = sql_generator.test_run
    test_run.set_progress(run_type, "Running")
    test_run.save()
    get_current_session().commit()

    def update_test_progress(progress: ThreadedProgress) -> None:
        test_run.set_progress(
            run_type,
            "Running",
            detail=f"{progress['processed']} of {progress['total']}",
            error=f"{progress['errors']} test{'s' if progress['errors'] > 1 else ''} had errors. See details in results."
            if progress["errors"]
            else None,
        )
        test_run.save()
        get_current_session().commit()

    LOG.info(f"Running {run_type} tests: {len(test_defs)}")
    test_results, error_data = job.fetch_threaded(
        [sql_generator.run_query_test(td) for td in test_defs],
        use_target_db=run_type != "METADATA",
        max_threads=sql_generator.connection.effective_max_threads,
        on_progress=update_test_progress if save_progress else None,
    )

    if test_results:
        LOG.info(f"Writing {run_type} test results")
        write_to_app_db(
            test_results,
            sql_generator.template_result_columns[run_type],
            sql_generator.test_results_table,
        )

    if error_count := len(error_data):
        LOG.warning(f"Errors running {run_type} tests: {error_count}")
        LOG.info(f"Writing {run_type} test errors")
        for index, error in error_data.items():
            test_defs[index].errors.append(error)

        error_results = sql_generator.get_test_errors(test_defs)
        write_to_app_db(error_results, sql_generator.result_columns, sql_generator.test_results_table)

    test_run.set_progress(
        run_type,
        "Warning" if error_count else "Completed",
        error=f"{error_count} test{'s' if error_count > 1 else ''} had errors"
        if error_count
        else None,
    )


def _run_cat_tests(
    job: StoppableJob,
    sql_generator: TestExecutionSQL,
    test_defs: list[TestExecutionDef],
    save_progress: bool = False,
) -> None:
    test_run = sql_generator.test_run
    test_run.set_progress("CAT", "Running")
    test_run.save()
    get_current_session().commit()

    total_count = len(test_defs)
    LOG.info(f"Aggregating CAT tests: {total_count}")
    aggregate_queries, aggregate_test_defs = sql_generator.aggregate_cat_tests(test_defs)

    def update_aggegate_progress(progress: ThreadedProgress) -> None:
        processed_count = sum(len(aggregate_test_defs[index]) for index in progress["indexes"])
        test_run.set_progress(
            "CAT",
            "Running",
            detail=f"{processed_count} of {total_count}",
            error=f"{progress['errors']} {'queries' if progress['errors'] > 1 else 'query'} had errors"
            if progress["errors"]
            else None,
        )
        test_run.save()
        get_current_session().commit()

    LOG.info(f"Running aggregated CAT test queries: {len(aggregate_queries)}")
    aggregate_results, aggregate_errors = job.fetch_threaded(
        aggregate_queries,
        use_target_db=True,
        max_threads=sql_generator.connection.effective_max_threads,
        on_progress=update_aggegate_progress if save_progress else None,
    )

    if aggregate_results:
        LOG.info("Writing aggregated CAT test results")
        test_results = sql_generator.get_cat_test_results(aggregate_results, aggregate_test_defs)
        write_to_app_db(test_results, sql_generator.result_columns, sql_generator.test_results_table)

    error_count = 0
    if aggregate_errors:
        LOG.warning(f"Errors running aggregated CAT test queries: {len(aggregate_errors)}")
        error_test_defs: list[TestExecutionDef] = []
        for index in aggregate_errors:
            error_test_defs.extend(aggregate_test_defs[index])

        single_queries, single_test_defs = sql_generator.aggregate_cat_tests(error_test_defs, single=True)

        test_run.set_progress(
            "CAT",
            "Running",
            error="Rerunning errored tests singly",
        )
        test_run.save()
        get_current_session().commit()

        def update_single_progress(progress: ThreadedProgress) -> None:
            test_run.set_progress(
                "CAT",
                "Running",
                error=(
                    f"Rerunning errored tests singly: {progress['processed']} of {progress['total']}"
                    f"\n{progress['errors']} test{'s' if progress['errors'] > 1 else ''} had errors" if progress["errors"] else ""
                ),
            )
            test_run.save()
            get_current_session().commit()

        LOG.info(f"Rerunning errored CAT tests singly: {len(single_test_defs)}")
        single_results, single_errors = job.fetch_threaded(
            single_queries,
            use_target_db=True,
            max_threads=sql_generator.connection.effective_max_threads,
            on_progress=update_single_progress if save_progress else None,
        )

        if single_results:
            LOG.info("Writing single CAT test results")
            test_results = sql_generator.get_cat_test_results(single_results, single_test_defs)
            write_to_app_db(test_results, sql_generator.result_columns, sql_generator.test_results_table)

        if error_count := len(single_errors):
            LOG.warning(f"Errors running CAT tests singly: {error_count}")
            LOG.info("Writing single CAT test errors")
            error_test_defs: list[TestExecutionDef] = []
            for index, error in single_errors.items():
                td = single_test_defs[index][0]
                td.errors.append(error)
                error_test_defs.append(td)

            error_results = sql_generator.get_test_errors(error_test_defs)
            write_to_app_db(error_results, sql_generator.result_columns, sql_generator.test_results_table)

    test_run.set_progress(
        "CAT",
        "Warning" if error_count else "Completed",
        error=f"{error_count} test{'s' if error_count > 1 else ''} had errors. See details in results."
        if error_count
        else None,
    )
