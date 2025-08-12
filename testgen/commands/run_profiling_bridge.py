import logging
import subprocess
import threading
import uuid
from datetime import UTC, datetime

import pandas as pd
from progress.spinner import Spinner

import testgen.common.process_service as process_service
from testgen import settings
from testgen.commands.queries.profiling_query import CProfilingSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.common import (
    date_service,
    execute_db_queries,
    fetch_dict_from_db,
    fetch_from_db_threaded,
    get_profiling_params,
    quote_csv_items,
    set_target_db_params,
    write_to_app_db,
)
from testgen.common.database.database_service import empty_cache
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.ui.session import session

LOG = logging.getLogger("testgen")


def save_contingency_rules(df_merged, threshold_ratio):
    # Prep rows to save
    lst_rules = []
    for row in df_merged.itertuples():
        # First causes second: almost all of first coincide with second value
        if row.pair_to_first_ratio >= threshold_ratio:
            profiling_run_id = row.profiling_run_id
            schema_name = row.schema_name
            table_name = row.table_name
            cause_column_name = row.first_column_name
            cause_column_value = getattr(row, row.first_column_name)
            effect_column_name = row.second_column_name
            effect_column_value = getattr(row, row.second_column_name)
            pair_count = row.pair_count
            cause_column_total = row.first_column_overall_count
            effect_column_total = row.second_column_overall_count
            rule_ratio = row.pair_to_first_ratio
            lst_rules.append(
                [
                    profiling_run_id,
                    schema_name,
                    table_name,
                    cause_column_name,
                    cause_column_value,
                    effect_column_name,
                    effect_column_value,
                    pair_count,
                    cause_column_total,
                    effect_column_total,
                    rule_ratio,
                ]
            )

        # Second causes first: almost all of second coincide with first value
        if row.pair_to_second_ratio >= threshold_ratio:
            profiling_run_id = row.profiling_run_id
            schema_name = row.schema_name
            table_name = row.table_name
            cause_column_name = row.second_column_name
            cause_column_value = getattr(row, row.second_column_name)
            effect_column_name = row.first_column_name
            effect_column_value = getattr(row, row.first_column_name)
            pair_count = row.pair_count
            cause_column_total = row.second_column_overall_count
            effect_column_total = row.first_column_overall_count
            rule_ratio = row.pair_to_second_ratio
            lst_rules.append(
                [
                    profiling_run_id,
                    schema_name,
                    table_name,
                    cause_column_name,
                    cause_column_value,
                    effect_column_name,
                    effect_column_value,
                    pair_count,
                    cause_column_total,
                    effect_column_total,
                    rule_ratio,
                ]
            )

    write_to_app_db(
        lst_rules,
        [
            "profile_run_id",
            "schema_name",
            "table_name",
            "cause_column_name",
            "cause_column_value",
            "effect_column_name",
            "effect_column_value",
            "pair_count",
            "cause_column_total",
            "effect_column_total",
            "rule_ratio",
        ],
        "profile_pair_rules",
    )


def RunPairwiseContingencyCheck(clsProfiling: CProfilingSQL, threshold_ratio: float):
    # Goal: identify pairs of values that represent IF X=A THEN Y=B rules

    # Define the threshold percent -- should be high
    if threshold_ratio:
        threshold_ratio = threshold_ratio / 100.0
    else:
        threshold_ratio = 0.95
    str_max_values = "6"

    # Retrieve columns to include in list from profiing results
    clsProfiling.contingency_max_values = str_max_values
    lst_tables = fetch_dict_from_db(*clsProfiling.GetContingencyColumns())

    # Retrieve record counts per column combination
    df_merged = None
    if lst_tables:
        for dct_table in lst_tables:
            df_merged = None
            clsProfiling.data_schema = dct_table["schema_name"]
            clsProfiling.data_table = dct_table["table_name"]
            clsProfiling.contingency_columns = quote_csv_items(dct_table["contingency_columns"])
            lst_counts = fetch_dict_from_db(*clsProfiling.GetContingencyCounts(), use_target_db=True)
            if lst_counts:
                df = pd.DataFrame(lst_counts)
                # Get list of columns
                columns = dct_table["contingency_columns"].lower().split(",")

                # Calculate overall counts for each column
                overall_counts = {col: df.groupby(col)["freq_ct"].sum() for col in columns}

                # Prepare to aggregate the data
                contingency_table = []
                for i, col1 in enumerate(columns):
                    for col2 in columns[i + 1 :]:
                        # Create a pivot table for each pair
                        pivot = df.pivot_table(index=col1, columns=col2, values="freq_ct", aggfunc="sum", fill_value=0)
                        pivot = pivot.stack().reset_index()
                        pivot.rename(columns={0: "pair_count"}, inplace=True)

                        # Add overall counts
                        pivot["first_column_overall_count"] = pivot[col1].map(overall_counts[col1])
                        pivot["second_column_overall_count"] = pivot[col2].map(overall_counts[col2])

                        # Add column names
                        pivot["first_column_name"] = col1
                        pivot["second_column_name"] = col2

                        contingency_table.append(pivot)

                # Combine all pairs into a single DataFrame
                contingency_table = pd.concat(contingency_table, ignore_index=True)

                # Calculate the ratios
                contingency_table["pair_to_first_ratio"] = (
                    contingency_table["pair_count"] / contingency_table["first_column_overall_count"]
                )
                contingency_table["pair_to_second_ratio"] = (
                    contingency_table["pair_count"] / contingency_table["second_column_overall_count"]
                )

                # Include rows where both cols meet minimum threshold count (max of 30 or 5%)
                total_observations = contingency_table["pair_count"].sum()
                threshold_min = max(total_observations * 0.05, 30)
                contingency_table = contingency_table[
                    (contingency_table["first_column_overall_count"] >= threshold_min)
                    & (contingency_table["second_column_overall_count"] >= threshold_min)
                ]
                # Drop rows where neither ratio meets the threshold ratio (keep if either meets it)
                #  -- note we still have to check individual columns when saving pairs
                contingency_table = contingency_table[
                    ~(
                        (contingency_table["pair_to_first_ratio"] < threshold_ratio)
                        & (contingency_table["pair_to_second_ratio"] < threshold_ratio)
                    )
                ]

                # Add table name
                contingency_table["profiling_run_id"] = clsProfiling.profile_run_id
                contingency_table["schema_name"] = dct_table["schema_name"]
                contingency_table["table_name"] = dct_table["table_name"]

                # Combine with previous tables
                if df_merged == None:
                    df_merged = contingency_table
                else:
                    df_merged = pd.concat([df_merged, contingency_table], ignore_index=True)

        if df_merged is not None:
            if not df_merged.empty:
                save_contingency_rules(df_merged, threshold_ratio)


def run_profiling_in_background(table_group_id):
    msg = f"Starting run_profiling_in_background against table group_id: {table_group_id}"
    if settings.IS_DEBUG:
        LOG.info(msg + ". Running in debug mode (new thread instead of new process).")
        empty_cache()
        background_thread = threading.Thread(
            target=run_profiling_queries,
            args=(table_group_id, session.username),
        )
        background_thread.start()
    else:
        LOG.info(msg)
        script = ["testgen", "run-profile", "-tg", str(table_group_id)]
        subprocess.Popen(script)  # NOQA S603


@with_database_session
def run_profiling_queries(table_group_id: str, username: str | None = None, spinner: Spinner | None = None):
    if table_group_id is None:
        raise ValueError("Table Group ID was not specified")

    has_errors = False

    # Set Project Connection Parms in common.db_bridgers from retrieved parms
    LOG.info("CurrentStep: Assigning Connection Parameters")
    connection = Connection.get_by_table_group(table_group_id)
    set_target_db_params(connection.__dict__)

    LOG.info("CurrentStep: Retrieving Parameters")

    # Generate UUID for Profile Run ID
    profiling_run_id = str(uuid.uuid4())

    params = get_profiling_params(table_group_id)

    LOG.info("CurrentStep: Initializing Query Generator")
    clsProfiling = CProfilingSQL(params["project_code"], connection.sql_flavor)

    # Set General Parms
    clsProfiling.table_groups_id = table_group_id
    clsProfiling.connection_id = connection.connection_id
    clsProfiling.profile_run_id = profiling_run_id
    clsProfiling.data_schema = params["table_group_schema"]
    clsProfiling.parm_table_set = params["profiling_table_set"]
    clsProfiling.parm_table_include_mask = params["profiling_include_mask"]
    clsProfiling.parm_table_exclude_mask = params["profiling_exclude_mask"]
    clsProfiling.profile_id_column_mask = params["profile_id_column_mask"]
    clsProfiling.profile_sk_column_mask = params["profile_sk_column_mask"]
    clsProfiling.profile_use_sampling = params["profile_use_sampling"]
    clsProfiling.profile_flag_cdes = params["profile_flag_cdes"]
    clsProfiling.profile_sample_percent = params["profile_sample_percent"]
    clsProfiling.profile_sample_min_count = params["profile_sample_min_count"]
    clsProfiling.process_id = process_service.get_current_process_id()

    # Add a record in profiling_runs table for the new profile
    execute_db_queries([clsProfiling.GetProfileRunInfoRecordsQuery()])
    if spinner:
        spinner.next()

    table_count = 0
    column_count = 0
    try:
        # Retrieve Column Metadata
        LOG.info("CurrentStep: Getting DDF from project")

        lstResult = fetch_dict_from_db(*clsProfiling.GetDDFQuery(), use_target_db=True)
        column_count = len(lstResult)

        if lstResult:
            # Get distinct tables
            distinct_tables = set()
            for item in lstResult:
                schema_name = item["table_schema"]
                table_name = item["table_name"]
                distinct_tables.add(f"{schema_name}.{table_name}")

            # Convert the set to a list
            distinct_tables_list = list(distinct_tables)
            table_count = len(distinct_tables_list)

            if clsProfiling.profile_use_sampling == "Y":
                # Sampling tables
                lstQueries = []
                for parm_sampling_table in distinct_tables_list:
                    clsProfiling.sampling_table = parm_sampling_table
                    lstQueries.append(clsProfiling.GetTableSampleCount())

                lstSampleTables, _, intErrors = fetch_from_db_threaded(
                    lstQueries, use_target_db=True, max_threads=connection.max_threads, spinner=spinner
                )
                dctSampleTables = {x[0]: [x[1], x[2], x[3]] for x in lstSampleTables}
                if intErrors > 0:
                    has_errors = True
                    LOG.warning(
                        f"Errors were encountered retrieving sampling table counts. ({intErrors} errors occurred.) Please check log."
                    )

            # Assemble profiling queries
            if spinner:
                spinner.next()
            LOG.info("CurrentStep: Assembling profiling queries, round 1")
            lstQueries = []
            for dctColumnRecord in lstResult:
                # Set Column Parms
                clsProfiling.data_schema = dctColumnRecord["table_schema"]
                clsProfiling.data_table = dctColumnRecord["table_name"]
                clsProfiling.col_name = dctColumnRecord["column_name"]
                clsProfiling.col_type = dctColumnRecord["data_type"]
                clsProfiling.profile_run_id = profiling_run_id
                clsProfiling.col_is_decimal = dctColumnRecord["is_decimal"]
                clsProfiling.col_ordinal_position = dctColumnRecord["ordinal_position"]
                clsProfiling.col_gen_type = dctColumnRecord["general_type"]
                clsProfiling.parm_do_sample = "N"

                if clsProfiling.profile_use_sampling == "Y":
                    if dctSampleTables[clsProfiling.data_schema + "." + clsProfiling.data_table][0] > -1:
                        clsProfiling.parm_sample_size = dctSampleTables[
                            clsProfiling.data_schema + "." + clsProfiling.data_table
                        ][0]
                        clsProfiling.sample_ratio = dctSampleTables[
                            clsProfiling.data_schema + "." + clsProfiling.data_table
                        ][1]
                        clsProfiling.sample_percent_calc = dctSampleTables[
                            clsProfiling.data_schema + "." + clsProfiling.data_table
                        ][2]
                        clsProfiling.parm_do_sample = clsProfiling.profile_use_sampling
                    else:
                        clsProfiling.parm_sample_size = 0
                        clsProfiling.sample_ratio = ""
                        clsProfiling.sample_percent_calc = ""

                lstQueries.append(clsProfiling.GetProfilingQuery())

            # Run Profiling Queries and save results
            LOG.info("CurrentStep: Profiling Round 1")
            LOG.debug("Running %s profiling queries", len(lstQueries))

            lstProfiles, colProfileNames, intErrors = fetch_from_db_threaded(
                lstQueries, use_target_db=True, max_threads=connection.max_threads, spinner=spinner
            )
            if intErrors > 0:
                has_errors = True
                LOG.warning(
                    f"Errors were encountered executing profiling queries. ({intErrors} errors occurred.) Please check log."
                )
            LOG.info("CurrentStep: Saving Round 1 profiling results to Metadata")
            write_to_app_db(lstProfiles, colProfileNames, "profile_results")

            if clsProfiling.profile_use_sampling == "Y":
                lstQueries = []
                for table_name, value in dctSampleTables.items():
                    if value[0] > -1:
                        clsProfiling.sampling_table = table_name
                        clsProfiling.sample_ratio = value[1]
                        lstQueries.append(clsProfiling.UpdateProfileResultsToEst())

                execute_db_queries(lstQueries)

            if clsProfiling.parm_do_freqs == "Y":
                lstUpdates = []
                # Get secondary profiling columns
                LOG.info("CurrentStep: Selecting columns for frequency analysis")
                lstResult = fetch_dict_from_db(*clsProfiling.GetSecondProfilingColumnsQuery())

                if lstResult:
                    # Assemble secondary profiling queries
                    #  - Freqs for columns not already freq'd, but with max actual value length under threshold
                    LOG.info("CurrentStep: Generating frequency queries")
                    lstQueries = []
                    for dctColumnRecord in lstResult:
                        clsProfiling.data_schema = dctColumnRecord["schema_name"]
                        clsProfiling.data_table = dctColumnRecord["table_name"]
                        clsProfiling.col_name = dctColumnRecord["column_name"]

                        lstQueries.append(clsProfiling.GetSecondProfilingQuery())
                    # Run secondary profiling queries
                    LOG.info("CurrentStep: Retrieving %s frequency results from project", len(lstQueries))
                    lstUpdates, colProfileNames, intErrors = fetch_from_db_threaded(
                        lstQueries, use_target_db=True, max_threads=connection.max_threads, spinner=spinner
                    )
                    if intErrors > 0:
                        has_errors = True
                        LOG.warning(
                            f"Errors were encountered executing frequency queries. ({intErrors} errors occurred.) Please check log."
                        )

                    if lstUpdates:
                        # Copy secondary results to DQ staging
                        LOG.info("CurrentStep: Writing frequency results to Staging")
                        write_to_app_db(lstUpdates, colProfileNames, "stg_secondary_profile_updates")

            LOG.info("CurrentStep: Generating profiling update queries")

            lstQueries = []
            lstAnomalyTypes = []

            if lstUpdates:
                # Run single update query, then delete from staging
                lstQueries.extend([
                    clsProfiling.GetSecondProfilingUpdateQuery(),
                    clsProfiling.GetSecondProfilingStageDeleteQuery(),
                ])
            lstQueries.extend([
                clsProfiling.GetDataTypeSuggestionUpdateQuery(),
                clsProfiling.GetFunctionalDataTypeUpdateQuery(),
                clsProfiling.GetFunctionalTableTypeStageQuery(),
                clsProfiling.GetFunctionalTableTypeUpdateQuery(),
                clsProfiling.GetPIIFlagUpdateQuery(),
            ])

            lstAnomalyTypes = fetch_dict_from_db(*clsProfiling.GetAnomalyTestTypesQuery())
            lstQueries.extend([
                query for test_type in lstAnomalyTypes if (query := clsProfiling.GetAnomalyTestQuery(test_type))
            ])
            lstQueries.extend([
                clsProfiling.GetAnomalyScoringQuery(test_type)
                for test_type in lstAnomalyTypes
                if test_type["dq_score_prevalence_formula"]
            ])
            lstQueries.append(clsProfiling.GetAnomalyStatsRefreshQuery())

            # Always runs last
            lstQueries.append(clsProfiling.GetDataCharsRefreshQuery())
            if clsProfiling.profile_flag_cdes:
                lstQueries.append(clsProfiling.GetCDEFlaggerQuery())

            LOG.info("CurrentStep: Running profiling update queries")
            execute_db_queries(lstQueries)

            if params["profile_do_pair_rules"] == "Y":
                LOG.info("CurrentStep: Compiling pairwise contingency rules")
                RunPairwiseContingencyCheck(clsProfiling, params["profile_pair_rule_pct"])
        else:
            LOG.info("No columns were selected to profile.")
    except Exception as e:
        has_errors = True
        sqlsplit = e.args[0].split("[SQL", 1)
        errorline = sqlsplit[0].replace("'", "''") if len(sqlsplit) > 0 else "unknown error"
        clsProfiling.exception_message = f"{type(e).__name__}: {errorline}"
        raise
    finally:
        LOG.info("Updating the profiling run record")
        execute_db_queries([clsProfiling.GetProfileRunInfoRecordUpdateQuery()])
        end_time = datetime.now(UTC)

        execute_db_queries([
            clsProfiling.GetAnomalyScoringRollupRunQuery(),
            clsProfiling.GetAnomalyScoringRollupTableGroupQuery(),
        ])
        run_refresh_score_cards_results(
            project_code=params["project_code"],
            add_history_entry=True,
            refresh_date=date_service.parse_now(clsProfiling.run_date),
        )

        MixpanelService().send_event(
            "run-profiling",
            source=settings.ANALYTICS_JOB_SOURCE,
            username=username,
            sql_flavor=clsProfiling.flavor,
            sampling=clsProfiling.profile_use_sampling == "Y",
            table_count=table_count,
            column_count=column_count,
            run_duration=(end_time - date_service.parse_now(clsProfiling.run_date)).total_seconds(),
            scoring_duration=(datetime.now(UTC) - end_time).total_seconds(),
        )

    return f"""
        Profiling completed {"with errors. Check log for details." if has_errors else "successfully."}
        Run ID: {profiling_run_id}
    """
