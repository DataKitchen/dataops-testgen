import logging
import subprocess
import threading
import uuid

import pandas as pd

import testgen.common.process_service as process_service
from testgen import settings
from testgen.commands.queries.profiling_query import CProfilingSQL
from testgen.common import (
    AssignConnectParms,
    QuoteCSVItems,
    RetrieveDBResultsToDictList,
    RetrieveProfilingParms,
    RunActionQueryList,
    RunThreadedRetrievalQueryList,
    WriteListToDB,
    date_service,
    read_template_sql_file,
)
from testgen.common.database.database_service import empty_cache

booClean = True
LOG = logging.getLogger("testgen")


def InitializeProfilingSQL(strProject, strSQLFlavor):
    return CProfilingSQL(strProject, strSQLFlavor)


def CompileAnomalyTestQueries(clsProfiling):
    str_query = clsProfiling.GetAnomalyTestTypesQuery()
    lst_tests = RetrieveDBResultsToDictList("DKTG", str_query)

    lst_queries = []
    for dct_test_type in lst_tests:
        str_query = clsProfiling.GetAnomalyTestQuery(dct_test_type)
        if str_query:
            lst_queries.append(str_query)

    return lst_queries


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

    WriteListToDB(
        "DKTG",
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


def RunPairwiseContingencyCheck(clsProfiling, threshold_ratio):
    # Goal: identify pairs of values that represent IF X=A THEN Y=B rules

    # Define the threshold percent -- should be high
    if threshold_ratio:
        threshold_ratio = threshold_ratio / 100.0
    else:
        threshold_ratio = 0.95
    str_max_values = "6"

    # Retrieve columns to include in list from profiing results
    clsProfiling.contingency_max_values = str_max_values
    str_query = clsProfiling.GetContingencyColumns()
    lst_tables = RetrieveDBResultsToDictList("DKTG", str_query)

    # Retrieve record counts per column combination
    df_merged = None
    if lst_tables:
        for dct_table in lst_tables:
            df_merged = None
            clsProfiling.data_schema = dct_table["schema_name"]
            clsProfiling.data_table = dct_table["table_name"]
            clsProfiling.contingency_columns = QuoteCSVItems(dct_table["contingency_columns"])
            str_query = clsProfiling.GetContingencyCounts()
            lst_counts = RetrieveDBResultsToDictList("PROJECT", str_query)
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
        background_thread = threading.Thread(target=run_profiling_queries, args=(table_group_id,))
        background_thread.start()
    else:
        LOG.info(msg)
        script = ["testgen", "run-profile", "-tg", table_group_id]
        subprocess.Popen(script)  # NOQA S603


def run_profiling_queries(strTableGroupsID, spinner=None):
    if strTableGroupsID is None:
        raise ValueError("Table Group ID was not specified")

    booErrors = False

    LOG.info("CurrentStep: Retrieving Parameters")

    # Generate UUID for Profile Run ID
    strProfileRunID = str(uuid.uuid4())

    dctParms = RetrieveProfilingParms(strTableGroupsID)

    LOG.info("CurrentStep: Initializing Query Generator")
    clsProfiling = InitializeProfilingSQL(dctParms["project_code"], dctParms["sql_flavor"])

    # Set Project Connection Parms in common.db_bridgers from retrieved parms
    LOG.info("CurrentStep: Assigning Connection Parms")
    AssignConnectParms(
        dctParms["project_code"],
        dctParms["connection_id"],
        dctParms["project_host"],
        dctParms["project_port"],
        dctParms["project_db"],
        dctParms["table_group_schema"],
        dctParms["project_user"],
        dctParms["sql_flavor"],
        dctParms["url"],
        dctParms["connect_by_url"],
        dctParms["connect_by_key"],
        dctParms["private_key"],
        dctParms["private_key_passphrase"],
        "PROJECT",
    )

    # Set General Parms
    clsProfiling.table_groups_id = strTableGroupsID
    clsProfiling.connection_id = dctParms["connection_id"]
    clsProfiling.parm_do_sample = "N"
    clsProfiling.parm_sample_size = 0
    clsProfiling.parm_vldb_flag = "N"
    clsProfiling.parm_do_freqs = "Y"
    clsProfiling.parm_max_freq_length = 25
    clsProfiling.parm_do_patterns = "Y"
    clsProfiling.parm_max_pattern_length = 25
    clsProfiling.profile_run_id = strProfileRunID
    clsProfiling.data_qc_schema = dctParms["project_qc_schema"]
    clsProfiling.data_schema = dctParms["table_group_schema"]
    clsProfiling.parm_table_set = dctParms["profiling_table_set"]
    clsProfiling.parm_table_include_mask = dctParms["profiling_include_mask"]
    clsProfiling.parm_table_exclude_mask = dctParms["profiling_exclude_mask"]
    clsProfiling.profile_id_column_mask = dctParms["profile_id_column_mask"]
    clsProfiling.profile_sk_column_mask = dctParms["profile_sk_column_mask"]
    clsProfiling.profile_use_sampling = dctParms["profile_use_sampling"]
    clsProfiling.profile_sample_percent = dctParms["profile_sample_percent"]
    clsProfiling.profile_sample_min_count = dctParms["profile_sample_min_count"]
    clsProfiling.process_id = process_service.get_current_process_id()

    # Add a record in profiling_runs table for the new profile
    strProfileRunQuery = clsProfiling.GetProfileRunInfoRecordsQuery()
    lstProfileRunQuery = [strProfileRunQuery]
    RunActionQueryList("DKTG", lstProfileRunQuery)
    if spinner:
        spinner.next()
    message = "Profiling completed "
    try:
        # Retrieve Column Metadata
        LOG.info("CurrentStep: Getting DDF from project")

        strQuery = clsProfiling.GetDDFQuery()
        lstResult = RetrieveDBResultsToDictList("PROJECT", strQuery)

        if len(lstResult) == 0:
            LOG.warning("SQL retrieved 0 records")

        if lstResult:
            if clsProfiling.profile_use_sampling == "Y":
                # Get distinct tables
                distinct_tables = set()
                for item in lstResult:
                    schema_name = item["table_schema"]
                    table_name = item["table_name"]
                    distinct_tables.add(f"{schema_name}.{table_name}")

                # Convert the set to a list
                distinct_tables_list = list(distinct_tables)

                # Sampling tables
                lstQueries = []
                for parm_sampling_table in distinct_tables_list:
                    clsProfiling.sampling_table = parm_sampling_table
                    strQuery = clsProfiling.GetTableSampleCount()
                    lstQueries.append(strQuery)

                lstSampleTables, _, intErrors = RunThreadedRetrievalQueryList(
                    "PROJECT", lstQueries, dctParms["max_threads"], spinner
                )
                dctSampleTables = {x[0]: [x[1], x[2]] for x in lstSampleTables}
                if intErrors > 0:
                    booErrors = True
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
                clsProfiling.profile_run_id = strProfileRunID
                clsProfiling.col_is_decimal = dctColumnRecord["is_decimal"]
                clsProfiling.col_ordinal_position = dctColumnRecord["ordinal_position"]
                clsProfiling.col_max_char_length = dctColumnRecord["character_maximum_length"]
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
                        clsProfiling.parm_do_sample = clsProfiling.profile_use_sampling
                    else:
                        clsProfiling.parm_sample_size = 0
                        clsProfiling.sample_ratio = ""

                strQuery = clsProfiling.GetProfilingQuery()
                lstQueries.append(strQuery)

            # Run Profiling Queries and save results
            LOG.info("CurrentStep: Profiling Round 1")
            LOG.debug("Running %s profiling queries", len(lstQueries))

            lstProfiles, colProfileNames, intErrors = RunThreadedRetrievalQueryList(
                "PROJECT", lstQueries, dctParms["max_threads"], spinner
            )
            if intErrors > 0:
                booErrors = True
                LOG.warning(
                    f"Errors were encountered executing profiling queries. ({intErrors} errors occurred.) Please check log."
                )
            LOG.info("CurrentStep: Saving Round 1 profiling results to Metadata")
            WriteListToDB("DKTG", lstProfiles, colProfileNames, "profile_results")

            if clsProfiling.profile_use_sampling == "Y":
                lstQueries = []
                for table_name, value in dctSampleTables.items():
                    if value[0] > -1:
                        clsProfiling.sampling_table = table_name
                        clsProfiling.sample_ratio = value[1]
                        strQuery = clsProfiling.UpdateProfileResultsToEst()
                        lstQueries.append(strQuery)

                RunActionQueryList("DKTG", lstQueries)

            if clsProfiling.parm_do_freqs == "Y":
                lstUpdates = []
                # Get secondary profiling columns
                LOG.info("CurrentStep: Selecting columns for frequency analysis")
                strQuery = clsProfiling.GetSecondProfilingColumnsQuery()
                lstResult = RetrieveDBResultsToDictList("DKTG", strQuery)

                if lstResult:
                    # Assemble secondary profiling queries
                    #  - Freqs for columns not already freq'd, but with max actual value length under threshold
                    LOG.info("CurrentStep: Generating frequency queries")
                    lstQueries = []
                    for dctColumnRecord in lstResult:
                        clsProfiling.data_schema = dctColumnRecord["schema_name"]
                        clsProfiling.data_table = dctColumnRecord["table_name"]
                        clsProfiling.col_name = dctColumnRecord["column_name"]

                        strQuery = clsProfiling.GetSecondProfilingQuery()
                        lstQueries.append(strQuery)
                    # Run secondary profiling queries
                    LOG.info("CurrentStep: Retrieving %s frequency results from project", len(lstQueries))
                    lstUpdates, colProfileNames, intErrors = RunThreadedRetrievalQueryList(
                        "PROJECT", lstQueries, dctParms["max_threads"], spinner
                    )
                    if intErrors > 0:
                        booErrors = True
                        LOG.warning(
                            f"Errors were encountered executing frequency queries. ({intErrors} errors occurred.) Please check log."
                        )

                    if lstUpdates:
                        # Copy secondary results to DQ staging
                        LOG.info("CurrentStep: Writing frequency results to Staging")
                        WriteListToDB("DKTG", lstUpdates, colProfileNames, "stg_secondary_profile_updates")

            LOG.info("CurrentStep: Generating profiling update queries")

            lstQueries = []

            if lstUpdates:
                # Run single update query, then delete from staging
                strQuery = clsProfiling.GetSecondProfilingUpdateQuery()
                lstQueries.append(strQuery)
                strQuery = clsProfiling.GetSecondProfilingStageDeleteQuery()
                lstQueries.append(strQuery)
            strQuery = clsProfiling.GetDataTypeSuggestionUpdateQuery()
            lstQueries.append(strQuery)
            strQuery = clsProfiling.GetFunctionalDataTypeUpdateQuery()
            lstQueries.append(strQuery)
            strQuery = clsProfiling.GetFunctionalTableTypeStageQuery()
            lstQueries.append(strQuery)
            strQuery = clsProfiling.GetFunctionalTableTypeUpdateQuery()
            lstQueries.append(strQuery)
            strQuery = clsProfiling.GetPIIFlagUpdateQuery()
            lstQueries.append(strQuery)
            lstQueries.extend(CompileAnomalyTestQueries(clsProfiling))
            strQuery = clsProfiling.GetAnomalyRefreshQuery()
            lstQueries.append(strQuery)
            # Always runs last
            strQuery = clsProfiling.GetDataCharsRefreshQuery()
            lstQueries.append(strQuery)

            LOG.info("CurrentStep: Running profiling update queries")
            RunActionQueryList("DKTG", lstQueries)

            if dctParms["profile_do_pair_rules"] == "Y":
                LOG.info("CurrentStep: Compiling pairwise contingency rules")
                RunPairwiseContingencyCheck(clsProfiling, dctParms["profile_pair_rule_pct"])
        else:
            LOG.info("No columns were selected to profile.")
    except Exception as e:
        booErrors = True
        sqlsplit = e.args[0].split("[SQL", 1)
        errorline = sqlsplit[0].replace("'", "''") if len(sqlsplit) > 0 else "unknown error"
        clsProfiling.exception_message = f"{type(e).__name__}: {errorline}"
        raise
    finally:
        LOG.info("Updating the profiling run record")
        lstProfileRunQuery = [clsProfiling.GetProfileRunInfoRecordUpdateQuery()]
        RunActionQueryList("DKTG", lstProfileRunQuery)
        if booErrors:
            str_error_status = "with errors. Check log for details."
        else:
            str_error_status = "successfully."
        message += str_error_status
    return message


def update_profile_run_status(profile_run_id, status):
    sql_template = read_template_sql_file("project_profile_run_record_update_status.sql", sub_directory="profiling")

    sql_template = sql_template.replace("{STATUS}", status)
    sql_template = sql_template.replace("{NOW}", date_service.get_now_as_string())
    sql_template = sql_template.replace("{EXCEPTION_MESSAGE}", "")
    sql_template = sql_template.replace("{PROFILE_RUN_ID}", profile_run_id)

    RunActionQueryList("DKTG", [sql_template])
