import logging
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Literal
from uuid import UUID

import testgen.common.process_service as process_service
from testgen import settings
from testgen.commands.queries.execute_tests_query import TestExecutionDef, TestExecutionSQL
from testgen.commands.queries.rollup_scores_query import RollupScoresSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.common import (
    execute_db_queries,
    fetch_dict_from_db,
    fetch_from_db_threaded,
    set_target_db_params,
    write_to_app_db,
)
from testgen.common.database.database_service import ThreadedProgress, empty_cache
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.common.notifications.test_run import send_test_run_notifications
from testgen.ui.session import session
from testgen.utils import get_exception_message

from .run_refresh_data_chars import run_data_chars_refresh
from .run_test_validation import run_test_validation

LOG = logging.getLogger("testgen")


def run_test_execution_in_background(test_suite_id: str | UUID):
    msg = f"Triggering test run for test suite {test_suite_id}"
    if settings.IS_DEBUG:
        LOG.info(msg + ". Running in debug mode (new thread instead of new process).")
        empty_cache()
        background_thread = threading.Thread(
            target=run_test_execution,
            args=(test_suite_id, session.auth.user_display if session.auth else None),
        )
        background_thread.start()
    else:
        LOG.info(msg)
        script = ["testgen", "run-tests", "--test-suite-id", str(test_suite_id)]
        subprocess.Popen(script)  # NOQA S603


@with_database_session
def run_test_execution(test_suite_id: str | UUID, username: str | None = None, run_date: datetime | None = None) -> str:
    if test_suite_id is None:
        raise ValueError("Test Suite ID was not specified")

    LOG.info(f"Starting test run for test suite {test_suite_id}")
    time_delta = (run_date - datetime.now(UTC)) if run_date else timedelta()

    LOG.info("Retrieving connection, table group, and test suite parameters")
    test_suite = TestSuite.get(test_suite_id)
    table_group = TableGroup.get(test_suite.table_groups_id)
    connection = Connection.get(table_group.connection_id)
    set_target_db_params(connection.__dict__)

    LOG.info("Creating test run record")
    test_run = TestRun(
        test_suite_id=test_suite_id,
        test_starttime=datetime.now(UTC) + time_delta,
        process_id=process_service.get_current_process_id(),
    )
    test_run.init_progress()
    test_run.set_progress("data_chars", "Running")
    test_run.save()

    try:
        LOG.info(f"Test run: {test_run.id}, Test suite: {test_suite.test_suite}, Table group: {table_group.table_groups_name}, Connection: {connection.connection_name}")
        data_chars = run_data_chars_refresh(connection, table_group, test_run.test_starttime)
        test_run.set_progress("data_chars", "Completed")

        sql_generator = TestExecutionSQL(connection, table_group, test_run)

        # Update the thresholds before retrieving the test definitions in the next steps
        LOG.info("Updating historic test thresholds")
        execute_db_queries([sql_generator.update_historic_thresholds()])

        LOG.info("Retrieving active test definitions in test suite")
        test_defs = fetch_dict_from_db(*sql_generator.get_active_test_definitions())
        test_defs = [TestExecutionDef(**item) for item in test_defs]

        if test_defs:
            LOG.info(f"Active test definitions: {len(test_defs)}")
            test_run.set_progress("validation", "Running")
            test_run.save()

            valid_test_defs = run_test_validation(sql_generator, test_defs)
            invalid_count = len(test_defs) - len(valid_test_defs)
            test_run.set_progress(
                "validation",
                "Warning" if invalid_count else "Completed",
                error=f"{invalid_count} test{'s' if invalid_count > 1 else ''} had errors. See details in results." if invalid_count else None,
            )

            if valid_test_defs:
                column_types = {(col.schema_name, col.table_name, col.column_name): col.column_type for col in data_chars}
                for td in valid_test_defs:
                    td.column_type = column_types.get((td.schema_name, td.table_name, td.column_name))

                run_functions = {
                    "QUERY": partial(_run_tests, sql_generator, "QUERY"),
                    "METADATA": partial(_run_tests, sql_generator, "METADATA"),
                    "CAT": partial(_run_cat_tests, sql_generator),
                }
                # Run metadata tests last so that results for other tests are available to them
                for run_type in ["QUERY", "CAT", "METADATA"]:
                    if (run_test_defs := [td for td in valid_test_defs if td.run_type == run_type]):
                        run_functions[run_type](run_test_defs)
                    else:
                        test_run.set_progress(run_type, "Completed")
                        LOG.info(f"No {run_type} tests to run")
            else:
                LOG.info("No valid tests to run")
        else:
            LOG.info("No active tests to run")

        LOG.info("Updating test results and test run")
        test_run.save()
        execute_db_queries(sql_generator.update_test_results())
        # Refresh needed because previous query updates the test run too
        test_run.refresh()

    except Exception as e:
        LOG.exception("Test execution encountered an error.")
        LOG.info("Setting test run status to Error")
        test_run.log_message = get_exception_message(e)
        test_run.test_endtime = datetime.now(UTC) + time_delta
        test_run.status = "Error"
        test_run.save()

        send_test_run_notifications(test_run)
    else:
        LOG.info("Setting test run status to Completed")
        test_run.test_endtime = datetime.now(UTC) + time_delta
        test_run.status = "Complete"
        test_run.save()

        LOG.info("Updating latest run for test suite")
        test_suite.last_complete_test_run_id = test_run.id
        test_suite.save()

        send_test_run_notifications(test_run)
        _rollup_test_scores(test_run, table_group)
    finally:
        MixpanelService().send_event(
            "run-tests",
            source=settings.ANALYTICS_JOB_SOURCE,
            username=username,
            sql_flavor=connection.sql_flavor_code,
            test_count=test_run.test_ct,
            run_duration=(test_run.test_endtime - test_run.test_starttime.replace(tzinfo=UTC)).total_seconds(),
            scoring_duration=(datetime.now(UTC) + time_delta - test_run.test_endtime).total_seconds(),
        )

    return f"""
        {"Test execution encountered an error. Check log for details." if test_run.status == "Error" else "Test execution completed."}
        Run ID: {test_run.id}
    """


def _run_tests(sql_generator: TestExecutionSQL, run_type: Literal["QUERY", "METADATA"], test_defs: list[TestExecutionDef]) -> None:
    test_run = sql_generator.test_run
    test_run.set_progress(run_type, "Running")
    test_run.save()

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

    LOG.info(f"Running {run_type} tests: {len(test_defs)}")
    test_results, result_columns, error_data = fetch_from_db_threaded(
        [sql_generator.run_query_test(td) for td in test_defs],
        use_target_db=run_type != "METADATA",
        max_threads=sql_generator.connection.max_threads,
        progress_callback=update_test_progress,
    )

    if test_results:
        LOG.info(f"Writing {run_type} test results")
        write_to_app_db(test_results, result_columns, sql_generator.test_results_table)

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


def _run_cat_tests(sql_generator: TestExecutionSQL, test_defs: list[TestExecutionDef]) -> None:
    test_run = sql_generator.test_run
    test_run.set_progress("CAT", "Running")
    test_run.save()

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

    LOG.info(f"Running aggregated CAT test queries: {len(aggregate_queries)}")
    aggregate_results, _, aggregate_errors = fetch_from_db_threaded(
        aggregate_queries,
        use_target_db=True,
        max_threads=sql_generator.connection.max_threads,
        progress_callback=update_aggegate_progress,
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

        LOG.info(f"Rerunning errored CAT tests singly: {len(single_test_defs)}")
        single_results, _, single_errors = fetch_from_db_threaded(
            single_queries,
            use_target_db=True,
            max_threads=sql_generator.connection.max_threads,
            progress_callback=update_single_progress,
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


def _rollup_test_scores(test_run: TestRun, table_group: TableGroup) -> None:
    try:
        LOG.info("Rolling up test scores")
        sql_generator = RollupScoresSQL(test_run.id, table_group.id)
        execute_db_queries(
            sql_generator.rollup_test_scores(update_prevalence=True, update_table_group=True),
        )
        run_refresh_score_cards_results(
            project_code=table_group.project_code,
            add_history_entry=True,
            refresh_date=test_run.test_starttime,
        )
    except Exception:
        LOG.exception("Error rolling up test scores")
