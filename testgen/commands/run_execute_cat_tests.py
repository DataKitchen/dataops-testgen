import logging
from datetime import UTC, datetime

from progress.spinner import Spinner

from testgen import settings
from testgen.commands.queries.execute_cat_tests_query import CCATExecutionSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.common import (
    date_service,
    execute_db_queries,
    fetch_dict_from_db,
    fetch_from_db_threaded,
    write_to_app_db,
)
from testgen.common.get_pipeline_parms import TestExecutionParams
from testgen.common.mixpanel_service import MixpanelService

LOG = logging.getLogger("testgen")


def FinalizeTestRun(clsCATExecute: CCATExecutionSQL, username: str | None = None):
    _, row_counts = execute_db_queries([
        clsCATExecute.FinalizeTestResultsSQL(),
        clsCATExecute.PushTestRunStatusUpdateSQL(),
        clsCATExecute.FinalizeTestSuiteUpdateSQL(),
    ])
    end_time = datetime.now(UTC)
    
    try:
        execute_db_queries([
            clsCATExecute.CalcPrevalenceTestResultsSQL(),
            clsCATExecute.TestScoringRollupRunSQL(),
            clsCATExecute.TestScoringRollupTableGroupSQL(),
        ])
        run_refresh_score_cards_results(
            project_code=clsCATExecute.project_code,
            add_history_entry=True,
            refresh_date=date_service.parse_now(clsCATExecute.run_date),
        )
    except Exception:
        LOG.exception("Error refreshing scores after test run")
        pass

    MixpanelService().send_event(
        "run-tests",
        source=settings.ANALYTICS_JOB_SOURCE,
        username=username,
        sql_flavor=clsCATExecute.flavor,
        test_count=row_counts[0],
        run_duration=(end_time - date_service.parse_now(clsCATExecute.run_date)).total_seconds(),
        scoring_duration=(datetime.now(UTC) - end_time).total_seconds(),
    )


def run_cat_test_queries(
    params: TestExecutionParams,
    test_run_id: str,
    test_time: str,
    project_code: str,
    test_suite: str,
    error_msg: str,
    username: str | None = None,
    minutes_offset: int = 0,
    spinner: Spinner | None = None
):
    has_errors = False

    LOG.info("CurrentStep: Initializing CAT Query Generator")
    clsCATExecute = CCATExecutionSQL(
        project_code, params["test_suite_id"], test_suite, params["sql_flavor"], params["max_query_chars"], minutes_offset
    )
    clsCATExecute.test_run_id = test_run_id
    clsCATExecute.run_date = test_time
    clsCATExecute.table_groups_id = params["table_groups_id"]
    clsCATExecute.exception_message += error_msg

    # START TEST EXECUTION

    if spinner:
        spinner.next()

    lstAllResults = []

    try:
        # Retrieve distinct target tables from metadata
        LOG.info("CurrentStep: Retrieving Target Tables")
        # Gets distinct list of tables to be tested, to aggregate tests by table, from dk db
        lstTables = fetch_dict_from_db(*clsCATExecute.GetDistinctTablesSQL())
        LOG.info("Test Tables Identified: %s", len(lstTables))

        if lstTables:
            LOG.info("CurrentStep: Aggregating CAT Tests per Table")
            for dctTable in lstTables:
                clsCATExecute.target_schema = dctTable["schema_name"]
                clsCATExecute.target_table = dctTable["table_name"]
                # Writes records of aggregated tests per table and sequence number
                # (to prevent table queries from getting too large) to dk db.
                execute_db_queries([clsCATExecute.GetAggregateTableTestSQL()])

            LOG.info("CurrentStep: Retrieving CAT Tests to Run")
            # Retrieves records of aggregated tests to run as queries from dk db
            lstCATParms = fetch_dict_from_db(*clsCATExecute.GetAggregateTestParmsSQL())

            lstCATQueries = []
            # Prepares CAT Queries and populates query list
            LOG.info("CurrentStep: Preparing CAT Queries")
            for dctCATQuery in lstCATParms:
                clsCATExecute.target_schema = dctCATQuery["schema_name"]
                clsCATExecute.target_table = dctCATQuery["table_name"]
                clsCATExecute.cat_test_params = dctCATQuery
                lstCATQueries.append(clsCATExecute.PrepCATQuerySQL())

            if lstCATQueries:
                LOG.info("CurrentStep: Performing CAT Tests")
                lstAllResults, lstResultColumnNames, intErrors = fetch_from_db_threaded(
                    lstCATQueries, use_target_db=True, max_threads=params["max_threads"], spinner=spinner
                )

                if lstAllResults:
                    LOG.info("CurrentStep: Saving CAT Results")
                    # Write aggregate result records to aggregate result table at dk db
                    write_to_app_db(lstAllResults, lstResultColumnNames, "working_agg_cat_results")
                    LOG.info("CurrentStep: Parsing CAT Results")
                    # Parses aggregate results to individual test_result records at dk db
                    execute_db_queries([clsCATExecute.GetCATResultsParseSQL()])
                    LOG.info("Test results successfully parsed.")
                if intErrors > 0:
                    has_errors = True
                    cat_error_msg = f"Errors were encountered executing aggregate tests. ({intErrors} errors occurred.) Please check log."
                    LOG.warning(cat_error_msg)
                    clsCATExecute.exception_message += cat_error_msg
        else:
            LOG.info("No valid tests were available to perform")

    except Exception as e:
        has_errors = True
        sqlsplit = e.args[0].split("[SQL", 1)
        errorline = sqlsplit[0].replace("'", "''") if len(sqlsplit) > 0 else "unknown error"
        clsCATExecute.exception_message += f"{type(e).__name__}: {errorline}"
        raise

    else:
        return has_errors

    finally:
        LOG.info("Finalizing test run")
        FinalizeTestRun(clsCATExecute, username)
