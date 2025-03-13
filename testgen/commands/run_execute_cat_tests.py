import logging

from testgen.commands.queries.execute_cat_tests_query import CCATExecutionSQL
from testgen.commands.run_refresh_score_cards_results import run_refresh_score_cards_results
from testgen.common import (
    RetrieveDBResultsToDictList,
    RunActionQueryList,
    RunThreadedRetrievalQueryList,
    WriteListToDB,
    date_service,
)

LOG = logging.getLogger("testgen")


def RetrieveTargetTables(clsCATExecute):
    # Gets distinct list of tables to be tested, to aggregate tests by table, from dk db
    strQuery = clsCATExecute.GetDistinctTablesSQL()
    lstTables = RetrieveDBResultsToDictList("DKTG", strQuery)

    if len(lstTables) == 0:
        LOG.info("0 tables in the list for CAT test execution.")

    return lstTables


def AggregateTableTests(clsCATExecute):
    # Writes records of aggregated tests per table and sequence number
    # (to prevent table queries from getting too large) to dk db.
    strQuery = clsCATExecute.GetAggregateTableTestSQL()
    lstQueries = [strQuery]
    RunActionQueryList("DKTG", lstQueries)


def RetrieveTestParms(clsCATExecute):
    # Retrieves records of aggregated tests to run as queries from dk db
    strQuery = clsCATExecute.GetAggregateTestParmsSQL()
    lstResults = RetrieveDBResultsToDictList("DKTG", strQuery)

    return lstResults


def PrepCATQueries(clsCATExecute, lstCATParms):
    # Prepares CAT Queries and populates query list
    LOG.info("CurrentStep: Preparing CAT Queries")
    lstQueries = []
    for dctCATQuery in lstCATParms:
        clsCATExecute.target_schema = dctCATQuery["schema_name"]
        clsCATExecute.target_table = dctCATQuery["table_name"]
        clsCATExecute.dctTestParms = dctCATQuery
        strQuery = clsCATExecute.PrepCATQuerySQL()
        lstQueries.append(strQuery)

    return lstQueries


def ParseCATResults(clsCATExecute):
    # Parses aggregate results to individual test_result records at dk db
    strQuery = clsCATExecute.GetCATResultsParseSQL()
    RunActionQueryList("DKTG", [strQuery])


def FinalizeTestRun(clsCATExecute: CCATExecutionSQL):
    lstQueries = [clsCATExecute.FinalizeTestResultsSQL(),
                  clsCATExecute.PushTestRunStatusUpdateSQL(),
                  clsCATExecute.FinalizeTestSuiteUpdateSQL(),
                  clsCATExecute.CalcPrevalenceTestResultsSQL(),
                  clsCATExecute.TestScoringRollupRunSQL(),
                  clsCATExecute.TestScoringRollupTableGroupSQL()]
    RunActionQueryList(("DKTG"), lstQueries)
    run_refresh_score_cards_results(
        project_code=clsCATExecute.project_code,
        add_history_entry=True,
        refresh_date=date_service.parse_now(clsCATExecute.run_date),
    )


def run_cat_test_queries(
    dctParms, strTestRunID, strTestTime, strProjectCode, strTestSuite, error_msg, minutes_offset=0, spinner=None
):
    booErrors = False

    LOG.info("CurrentStep: Initializing CAT Query Generator")
    clsCATExecute = CCATExecutionSQL(
        strProjectCode, dctParms["test_suite_id"], strTestSuite, dctParms["sql_flavor"], dctParms["max_query_chars"], minutes_offset
    )
    clsCATExecute.test_run_id = strTestRunID
    clsCATExecute.run_date = strTestTime
    clsCATExecute.table_groups_id = dctParms["table_groups_id"]
    clsCATExecute.exception_message += error_msg

    # START TEST EXECUTION

    if spinner:
        spinner.next()

    lstAllResults = []

    try:
        # Retrieve distinct target tables from metadata
        LOG.info("CurrentStep: Retrieving Target Tables")
        lstTables = RetrieveTargetTables(clsCATExecute)
        LOG.info("Test Tables Identified: %s", len(lstTables))

        if lstTables:
            LOG.info("CurrentStep: Aggregating CAT Tests per Table")
            for dctTable in lstTables:
                clsCATExecute.target_schema = dctTable["schema_name"]
                clsCATExecute.target_table = dctTable["table_name"]
                AggregateTableTests(clsCATExecute)

            LOG.info("CurrentStep: Retrieving CAT Tests to Run")
            lstCATParms = RetrieveTestParms(clsCATExecute)

            lstCATQueries = PrepCATQueries(clsCATExecute, lstCATParms)
            if lstCATQueries:
                LOG.info("CurrentStep: Performing CAT Tests")
                lstAllResults, lstResultColumnNames, intErrors = RunThreadedRetrievalQueryList(
                    "PROJECT", lstCATQueries, dctParms["max_threads"], spinner
                )

                if lstAllResults:
                    LOG.info("CurrentStep: Saving CAT Results")
                    # Write aggregate result records to aggregate result table at dk db
                    WriteListToDB("DKTG", lstAllResults, lstResultColumnNames, "working_agg_cat_results")
                    LOG.info("CurrentStep: Parsing CAT Results")
                    ParseCATResults(clsCATExecute)
                    LOG.info("Test results successfully parsed.")
                if intErrors > 0:
                    booErrors = True
                    cat_error_msg = f"Errors were encountered executing aggregate tests. ({intErrors} errors occurred.) Please check log."
                    LOG.warning(cat_error_msg)
                    clsCATExecute.exception_message += cat_error_msg
        else:
            LOG.info("No valid tests were available to perform")

    except Exception as e:
        booErrors = True
        sqlsplit = e.args[0].split("[SQL", 1)
        errorline = sqlsplit[0].replace("'", "''") if len(sqlsplit) > 0 else "unknown error"
        clsCATExecute.exception_message += f"{type(e).__name__}: {errorline}"
        raise

    else:
        return booErrors

    finally:
        LOG.info("Finalizing test run")
        FinalizeTestRun(clsCATExecute)
