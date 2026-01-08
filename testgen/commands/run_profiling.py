import logging
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID

import testgen.common.process_service as process_service
from testgen import settings
from testgen.commands.queries.profiling_query import HygieneIssueType, ProfilingSQL, TableSampling
from testgen.commands.queries.refresh_data_chars_query import ColumnChars
from testgen.commands.queries.rollup_scores_query import RollupScoresSQL
from testgen.commands.run_generate_tests import run_test_gen_queries
from testgen.commands.run_refresh_data_chars import run_data_chars_refresh
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.commands.run_test_execution import run_test_execution_in_background
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
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.notifications.profiling_run import send_profiling_run_notifications
from testgen.ui.session import session
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")


def run_profiling_in_background(table_group_id: str | UUID) -> None:
    msg = f"Triggering profiling run for table group {table_group_id}"
    if settings.IS_DEBUG:
        LOG.info(msg + ". Running in debug mode (new thread instead of new process).")
        empty_cache()
        background_thread = threading.Thread(
            target=run_profiling,
            args=(table_group_id, session.auth.user_display if session.auth else None),
        )
        background_thread.start()
    else:
        LOG.info(msg)
        script = ["testgen", "run-profile", "-tg", str(table_group_id)]
        subprocess.Popen(script)  # NOQA S603


@with_database_session
def run_profiling(table_group_id: str | UUID, username: str | None = None, run_date: datetime | None = None) -> str:
    if table_group_id is None:
        raise ValueError("Table Group ID was not specified")

    LOG.info(f"Starting profiling run for table group {table_group_id}")
    time_delta = (run_date - datetime.now(UTC)) if run_date else timedelta()

    LOG.info("Retrieving connection and table group parameters")
    table_group = TableGroup.get(table_group_id)
    connection = Connection.get(table_group.connection_id)
    set_target_db_params(connection.__dict__)

    LOG.info("Creating profiling run record")
    profiling_run = ProfilingRun(
        project_code=table_group.project_code,
        connection_id=connection.connection_id,
        table_groups_id=table_group.id,
        profiling_starttime=datetime.now(UTC) + time_delta,
        process_id=process_service.get_current_process_id(),
    )
    profiling_run.init_progress()
    profiling_run.set_progress("data_chars", "Running")
    profiling_run.save()

    LOG.info(f"Profiling run: {profiling_run.id}, Table group: {table_group.table_groups_name}, Connection: {connection.connection_name}")
    try:
        data_chars = run_data_chars_refresh(connection, table_group, profiling_run.profiling_starttime)
        distinct_tables = {(column.table_name, column.record_ct) for column in data_chars}

        profiling_run.set_progress("data_chars", "Completed")
        profiling_run.table_ct = len(distinct_tables)
        profiling_run.column_ct = len(data_chars)
        profiling_run.record_ct = sum(table[1] for table in distinct_tables)
        profiling_run.data_point_ct = sum(column.record_ct for column in data_chars)

        if data_chars:
            sql_generator = ProfilingSQL(connection, table_group, profiling_run)

            _run_column_profiling(sql_generator, data_chars)
            _run_frequency_analysis(sql_generator)
            _run_hygiene_issue_detection(sql_generator)

            # if table_group.profile_do_pair_rules == "Y":
            #     LOG.info("Compiling pairwise contingency rules")
            #     run_pairwise_contingency_check(profiling_run.id, table_group.profile_pair_rule_pct)
        else:
            LOG.info("No columns were selected to profile.")
    except Exception as e:
        LOG.exception("Profiling encountered an error.")
        LOG.info("Setting profiling run status to Error")
        profiling_run.log_message = get_exception_message(e)
        profiling_run.profiling_endtime = datetime.now(UTC) + time_delta
        profiling_run.status = "Error"
        profiling_run.save()

        send_profiling_run_notifications(profiling_run)
    else:
        LOG.info("Setting profiling run status to Completed")
        profiling_run.profiling_endtime = datetime.now(UTC) + time_delta
        profiling_run.status = "Complete"
        profiling_run.save()

        send_profiling_run_notifications(profiling_run)

        _rollup_profiling_scores(profiling_run, table_group)

        if bool(table_group.monitor_test_suite_id) and not table_group.last_complete_profile_run_id:
            _generate_monitor_tests(table_group_id, table_group.monitor_test_suite_id)
    finally:
        MixpanelService().send_event(
            "run-profiling",
            source=settings.ANALYTICS_JOB_SOURCE,
            username=username,
            sql_flavor=connection.sql_flavor_code,
            sampling=table_group.profile_use_sampling,
            table_count=profiling_run.table_ct or 0,
            column_count=profiling_run.column_ct or 0,
            run_duration=(profiling_run.profiling_endtime - profiling_run.profiling_starttime).total_seconds(),
            scoring_duration=(datetime.now(UTC) + time_delta - profiling_run.profiling_endtime).total_seconds(),
        )

    return f"""
        {"Profiling encountered an error. Check log for details." if profiling_run.status == "Error" else "Profiling completed."}
        Run ID: {profiling_run.id}
    """


def _run_column_profiling(sql_generator: ProfilingSQL, data_chars: list[ColumnChars]) -> None:
    profiling_run = sql_generator.profiling_run
    profiling_run.set_progress("col_profiling", "Running")
    profiling_run.save()

    LOG.info(f"Running column profiling queries: {len(data_chars)}")
    table_group = sql_generator.table_group
    sampling_params: dict[str, TableSampling] = {}
    sample_percent = (
        float(table_group.profile_sample_percent)
        if str(table_group.profile_sample_percent).replace(".", "", 1).isdigit()
        else 30
    )
    if table_group.profile_use_sampling and 0 < sample_percent < 100:
        min_sample = table_group.profile_sample_min_count
        max_sample = 999000
        for column in data_chars:
            if not sampling_params.get(column.table_name) and column.record_ct > min_sample:
                calc_sample = round(sample_percent * column.record_ct / 100)
                sample_count = min(max(calc_sample, min_sample), max_sample)

                sampling_params[column.table_name] = TableSampling(
                    table_name=column.table_name,
                    sample_count=sample_count,
                    sample_ratio=column.record_ct / sample_count,
                    sample_percent=round(100 * sample_count / column.record_ct, 4),
                )

    def update_column_progress(progress: ThreadedProgress) -> None:
        profiling_run.set_progress(
            "col_profiling",
            "Running",
            detail=f"{progress['processed']} of {progress['total']}",
            error=f"{progress['errors']} column{'s' if progress['errors'] > 1 else ''} had errors"
            if progress["errors"]
            else None,
        )
        profiling_run.save()

    profiling_results, result_columns, error_data = fetch_from_db_threaded(
        [sql_generator.run_column_profiling(column, sampling_params.get(column.table_name)) for column in data_chars],
        use_target_db=True,
        max_threads=sql_generator.connection.max_threads,
        progress_callback=update_column_progress,
    )

    if error_count := len(error_data):
        LOG.warning(f"Errors running column profiling queries: {error_count}")
        LOG.info("Writing column profiling errors")
        error_results = sql_generator.get_profiling_errors(
            [(data_chars[index], error) for index, error in error_data.items()]
        )
        write_to_app_db(error_results, sql_generator.error_columns, sql_generator.profiling_results_table)

    if not profiling_results:  # All queries failed, so stop the process
        raise RuntimeError(f"{error_count} errors during column profiling. See details in results.")

    LOG.info("Writing column profiling results")
    write_to_app_db(profiling_results, result_columns, sql_generator.profiling_results_table)

    if sampling_params:
        try:
            LOG.info("Updating sampled profiling results")
            execute_db_queries(
                [
                    sql_generator.update_sampled_profiling_results(table_sampling)
                    for table_sampling in sampling_params.values()
                ]
            )
        except Exception as e:
            raise RuntimeError(f"Error updating sampled profiling results. {get_exception_message(e)}") from e

    profiling_run.set_progress(
        "col_profiling",
        "Warning" if error_count else "Completed",
        error=f"{error_count} column{'s' if error_count > 1 else ''} had errors. See details in results."
        if error_count
        else None,
    )


def _run_frequency_analysis(sql_generator: ProfilingSQL) -> None:
    profiling_run = sql_generator.profiling_run
    profiling_run.set_progress("freq_analysis", "Running")
    profiling_run.save()

    error_data = None
    try:
        LOG.info("Selecting columns for frequency analysis")
        frequency_columns = fetch_dict_from_db(*sql_generator.get_frequency_analysis_columns())

        if frequency_columns:
            LOG.info(f"Running frequency analysis queries: {len(frequency_columns)}")

            def update_frequency_progress(progress: ThreadedProgress) -> None:
                profiling_run.set_progress(
                    "freq_analysis", "Running", detail=f"{progress['processed']} of {progress['total']}"
                )
                profiling_run.save()

            frequency_results, result_columns, error_data = fetch_from_db_threaded(
                [sql_generator.run_frequency_analysis(ColumnChars(**column)) for column in frequency_columns],
                use_target_db=True,
                max_threads=sql_generator.connection.max_threads,
                progress_callback=update_frequency_progress,
            )
            if error_data:
                LOG.warning(f"Errors running frequency analysis queries: {len(error_data)}")

            if frequency_results:
                LOG.info("Writing frequency results to staging")
                write_to_app_db(frequency_results, result_columns, sql_generator.frequency_staging_table)

                LOG.info("Updating profiling results with frequency analysis and deleting staging")
                execute_db_queries(sql_generator.update_frequency_analysis_results())
    except Exception as e:
        profiling_run.set_progress("freq_analysis", "Warning", error=f"Error encountered. {get_exception_message(e)}")
    else:
        if error_data:
            profiling_run.set_progress(
                "freq_analysis", "Warning", error=f"Error encountered. {next(iter(error_data.values()))}"
            )
        else:
            profiling_run.set_progress("freq_analysis", "Completed")


def _run_hygiene_issue_detection(sql_generator: ProfilingSQL) -> None:
    profiling_run = sql_generator.profiling_run
    profiling_run.set_progress("hygiene_issues", "Running")
    profiling_run.save()

    try:
        LOG.info("Detecting functional data types and critical data elements")
        execute_db_queries(sql_generator.update_profiling_results())

        LOG.info("Retrieving hygiene issue types")
        hygiene_issue_types = fetch_dict_from_db(*sql_generator.get_hygiene_issue_types())
        hygiene_issue_types = [HygieneIssueType(**item) for item in hygiene_issue_types]

        LOG.info("Detecting hygiene issues and updating prevalence and counts")
        execute_db_queries(
            [
                *[
                    query
                    for issue_type in hygiene_issue_types
                    if (query := sql_generator.detect_hygiene_issue(issue_type))
                ],
                *[
                    sql_generator.update_hygiene_issue_prevalence(issue_type)
                    for issue_type in hygiene_issue_types
                    if issue_type.dq_score_prevalence_formula
                ],
                sql_generator.update_hygiene_issue_counts(),
            ]
        )
    except Exception as e:
        profiling_run.set_progress("hygiene_issues", "Warning", error=f"Error encountered. {get_exception_message(e)}")
    else:
        profiling_run.set_progress("hygiene_issues", "Completed")


def _rollup_profiling_scores(profiling_run: ProfilingRun, table_group: TableGroup) -> None:
    try:
        LOG.info("Rolling up profiling scores")
        execute_db_queries(
            RollupScoresSQL(profiling_run.id, table_group.id).rollup_profiling_scores(),
        )
        run_refresh_score_cards_results(
            project_code=table_group.project_code,
            add_history_entry=True,
            refresh_date=profiling_run.profiling_starttime,
        )
    except Exception:
        LOG.exception("Error rolling up profiling scores")


@with_database_session
def _generate_monitor_tests(table_group_id: str, test_suite_id: str) -> None:
    try:
        monitor_test_suite = TestSuite.get(test_suite_id)
        if not monitor_test_suite:
            LOG.info("Skipping test generation on missing monitor test suite")
        else:
            LOG.info("Generating monitor tests")
            run_test_gen_queries(table_group_id, monitor_test_suite.test_suite, "Monitor")
            run_test_execution_in_background(test_suite_id)
    except Exception:
        LOG.exception("Error generating monitor tests")
