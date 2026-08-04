import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from testgen.commands.queries.profiling_query import (
    HygieneIssueType,
    ProfilingSQL,
    TableSampling,
    calculate_sampling_params,
)
from testgen.commands.run_refresh_data_chars import run_data_chars_refresh
from testgen.commands.test_generation import run_monitor_generation, run_test_generation
from testgen.common import (
    execute_db_queries,
    fetch_dict_from_db,
    set_target_db_params,
)
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import (
    get_flavor_service,
    run_keyed_worker_pool,
)
from testgen.common.job_context import job_context
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.profile_frequency import build_frequent_values, with_frequent_patterns
from testgen.utils import get_exception_message

LOG = logging.getLogger("testgen")


@with_database_session
def run_profiling(
    table_group_id: str | UUID,
    username: str | None = None,
    run_date: datetime | None = None,
) -> UUID:
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
        id=job_context.get().job_id,
        project_code=table_group.project_code,
        connection_id=connection.connection_id,
        table_groups_id=table_group.id,
        profiling_starttime=datetime.now(UTC) + time_delta,
    )

    # This runs in a subprocess — commit after every save so progress is visible
    # to the UI (separate session) and to execute_db_queries (independent connection).
    session = get_current_session()

    profiling_run.init_progress()
    profiling_run.set_progress("data_chars", "Running")
    profiling_run.save()
    session.commit()

    LOG.info(f"Profiling run: {profiling_run.id}, Table group: {table_group.table_groups_name}, Connection: {connection.connection_name}")
    try:
        data_chars = run_data_chars_refresh(connection, table_group, profiling_run.profiling_starttime)
        if table_group.profile_exclude_xde:
            data_chars = _exclude_xde_columns(data_chars, table_group.id)
        distinct_tables = {(column.table_name, column.record_ct) for column in data_chars}

        profiling_run.set_progress("data_chars", "Completed")
        profiling_run.table_ct = len(distinct_tables)
        profiling_run.column_ct = len(data_chars)
        profiling_run.record_ct = sum(table[1] for table in distinct_tables)
        profiling_run.data_point_ct = sum(column.record_ct for column in data_chars)

        if data_chars:
            sql_generator = ProfilingSQL(connection, table_group, profiling_run)

            # Table record counts drive the deterministic largest-work-first key ordering
            # of both threaded passes.
            table_record_counts = {column.table_name: column.record_ct for column in data_chars}

            sampling_params = _compute_sampling_params(sql_generator, data_chars)
            _run_column_profiling(sql_generator, data_chars, sampling_params, table_record_counts)
            _run_frequency_analysis(sql_generator, sampling_params, table_record_counts)
            _run_hygiene_issue_detection(sql_generator)

            # if table_group.profile_do_pair_rules == "Y":
            #     LOG.info("Compiling pairwise contingency rules")
            #     run_pairwise_contingency_check(profiling_run.id, table_group.profile_pair_rule_pct)
        else:
            LOG.info("No columns were selected to profile.")
    except Exception:
        LOG.exception("Profiling encountered an error.")
        end_time = datetime.now(UTC) + time_delta
        raise
    else:
        end_time = datetime.now(UTC) + time_delta
        profiling_run.save()
        session.commit()

        _generate_tests(table_group)
    finally:
        MixpanelService().send_event(
            "run-profiling",
            source=job_context.get().source.upper(),
            username=username,
            sql_flavor=connection.sql_flavor_code,
            sampling=table_group.profile_use_sampling,
            table_count=profiling_run.table_ct or 0,
            column_count=profiling_run.column_ct or 0,
            run_duration=(end_time - profiling_run.profiling_starttime.replace(tzinfo=UTC)).total_seconds(),
        )

    return profiling_run.id


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


def _compute_sampling_params(
    sql_generator: ProfilingSQL, data_chars: list[ColumnChars]
) -> dict[str, TableSampling]:
    table_group = sql_generator.table_group
    sampling_params: dict[str, TableSampling] = {}
    if not table_group.profile_use_sampling:
        return sampling_params

    sampleable_types = get_flavor_service(sql_generator.flavor).sampleable_object_types
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

    A stable sort keeps the processing reproducible. Ordering does not affect
    results; Largest tables first helps the threads to finish about the same
    time.
    """
    return sorted(columns, key=lambda column: table_record_counts.get(column.table_name, 0), reverse=True)


def _write_column_error(sql_generator: ProfilingSQL, column: ColumnChars, error: str) -> None:
    error_row = sql_generator.get_profiling_errors([(column, error)])[0]
    ProfileResult.upsert(dict(zip(sql_generator.error_columns, error_row, strict=True)))


def _run_column_profiling(
    sql_generator: ProfilingSQL,
    data_chars: list[ColumnChars],
    sampling_params: dict[str, TableSampling],
    table_record_counts: dict[str, int],
) -> None:
    profiling_run = sql_generator.profiling_run
    profiling_run.set_progress("col_profiling", "Running")
    profiling_run.save()
    session = get_current_session()
    session.commit()

    columns = _order_largest_work_first(data_chars, table_record_counts)
    LOG.info(f"Running column profiling queries: {len(columns)}")

    # Build queries here, not in the worker, so the ORM session is only touched on this thread.
    work = [
        (column, sql_generator.run_column_profiling(column, sampling_params.get(column.table_name)))
        for column in columns
    ]
    total = len(work)
    error_count = 0

    for processed, outcome in enumerate(
        run_keyed_worker_pool(
            work,
            lambda built: fetch_dict_from_db(*built, use_target_db=True),
            max_threads=sql_generator.connection.max_threads,
        ),
        start=1,
    ):
        column = outcome.key
        error = outcome.error
        if error is None and outcome.result:
            try:
                ProfileResult.upsert(with_frequent_patterns(outcome.result[0]))
            except Exception as e:
                error = get_exception_message(e)
                LOG.exception("Error writing column profiling result")
        if error is not None:
            error_count += 1
            _write_column_error(sql_generator, column, error)

        profiling_run.set_progress(
            "col_profiling",
            "Running",
            detail=f"{processed} of {total}",
            error=f"{error_count} column{'s' if error_count > 1 else ''} had errors" if error_count else None,
        )
        profiling_run.save()
        session.commit()

    if error_count:
        LOG.warning(f"Errors running column profiling queries: {error_count}")

    if error_count == total:  # All queries failed, so stop the process
        raise RuntimeError(f"{error_count} errors during column profiling. See details in results.")

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


def _run_frequency_analysis(
    sql_generator: ProfilingSQL,
    sampling_params: dict[str, TableSampling],
    table_record_counts: dict[str, int],
) -> None:
    profiling_run = sql_generator.profiling_run
    profiling_run.set_progress("freq_analysis", "Running")
    profiling_run.save()
    session = get_current_session()
    session.commit()

    error_count = 0
    first_error: str | None = None
    try:
        LOG.info("Selecting columns for frequency analysis")
        frequency_columns = [ColumnChars(**column) for column in fetch_dict_from_db(*sql_generator.get_frequency_analysis_columns())]

        if frequency_columns:
            frequency_columns = _order_largest_work_first(frequency_columns, table_record_counts)
            LOG.info(f"Running frequency analysis queries: {len(frequency_columns)}")

            work = [
                (column, sql_generator.run_frequency_analysis(column, sampling_params.get(column.table_name)))
                for column in frequency_columns
            ]
            total = len(work)

            for processed, outcome in enumerate(
                run_keyed_worker_pool(
                    work,
                    lambda built: fetch_dict_from_db(*built, use_target_db=True),
                    max_threads=sql_generator.connection.max_threads,
                ),
                start=1,
            ):
                column = outcome.key
                error = outcome.error
                if error is None and outcome.result:
                    try:
                        _write_frequency_result(sql_generator, column, outcome.result)
                    except Exception as e:
                        error = get_exception_message(e)
                        LOG.exception("Error writing frequency analysis result")
                if error is not None:
                    error_count += 1
                    first_error = first_error or error

                profiling_run.set_progress("freq_analysis", "Running", detail=f"{processed} of {total}")
                profiling_run.save()
                session.commit()

            if error_count:
                LOG.warning(f"Errors running frequency analysis queries: {error_count}")
    except Exception as e:
        LOG.exception("Error running frequency analysis")
        profiling_run.set_progress("freq_analysis", "Warning", error=f"Error encountered. {get_exception_message(e)}")
    else:
        if error_count:
            profiling_run.set_progress("freq_analysis", "Warning", error=f"Error encountered. {first_error}")
        else:
            profiling_run.set_progress("freq_analysis", "Completed")


def _run_hygiene_issue_detection(sql_generator: ProfilingSQL) -> None:
    profiling_run = sql_generator.profiling_run
    profiling_run.set_progress("hygiene_issues", "Running")
    profiling_run.save()
    get_current_session().commit()

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
        LOG.exception("Error detecting hygiene issues")
        profiling_run.set_progress("hygiene_issues", "Warning", error=f"Error encountered. {get_exception_message(e)}")
    else:
        profiling_run.set_progress("hygiene_issues", "Completed")


@with_database_session
def _generate_tests(table_group: TableGroup) -> None:
    is_first_profile_run = not table_group.last_complete_profile_run_id

    if bool(table_group.monitor_test_suite_id):
        monitor_suite = TestSuite.get(table_group.monitor_test_suite_id)
        try:
            run_monitor_generation(
                table_group.monitor_test_suite_id,
                # Only Freshness depends on profiling results
                ["Freshness_Trend"],
                # Insert for new tables only, if user disabled regeneration
                mode="upsert" if is_first_profile_run or monitor_suite.monitor_regenerate_freshness else "insert",
            )
        except Exception:
            LOG.exception("Error generating Freshness monitors")

    if is_first_profile_run and bool(table_group.default_test_suite_id):
        try:
            run_test_generation(table_group.default_test_suite_id, "Standard")
        except Exception:
            LOG.exception(f"Error generating tests for test suite: {table_group.default_test_suite_id}")
