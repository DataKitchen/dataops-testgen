import logging

from testgen.commands.queries.execute_cat_tests_query import CCATExecutionSQL
from testgen.common import (
    AssignConnectParms,
    RetrieveDBResultsToDictList,
    RetrieveTestExecParms,
    RunActionQueryList,
    RunThreadedRetrievalQueryList,
    WriteListToDB,
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


def FinalizeTestRun(clsCATExecute):
    lstQueries = [clsCATExecute.FinalizeTestResultsSQL(), clsCATExecute.PushTestRunStatusUpdateSQL()]
    RunActionQueryList(("DKTG"), lstQueries)


def run_cat_test_queries(
    strTestRunID, strTestTime, strProjectCode, strTestSuite, error_msg, minutes_offset=0, spinner=None
):
    # PARAMETERS AND SET-UP
    booErrors = False
    LOG.info("CurrentStep: Retrieving Parameters")

    dctParms = RetrieveTestExecParms(strProjectCode, strTestSuite)

    LOG.info("CurrentStep: Initializing CAT Query Generator")
    clsCATExecute = CCATExecutionSQL(
        strProjectCode, dctParms["test_suite_id"], strTestSuite, dctParms["sql_flavor"], dctParms["max_query_chars"], minutes_offset
    )
    clsCATExecute.test_run_id = strTestRunID
    clsCATExecute.run_date = strTestTime
    clsCATExecute.exception_message += error_msg

    # Set Project Connection Params in common.db_bridgers from retrieved params
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
                clsCATExecute.replace_qc_schema = dctTable["replace_qc_schema"]
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
