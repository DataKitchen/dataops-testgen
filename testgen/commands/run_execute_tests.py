import logging
import subprocess
import threading
import uuid

from progress.spinner import Spinner

import testgen.common.process_service as process_service
from testgen import settings
from testgen.commands.queries.execute_tests_query import CTestExecutionSQL
from testgen.common import (
    AssignConnectParms,
    RetrieveDBResultsToDictList,
    RetrieveTestExecParms,
    RunActionQueryList,
    RunThreadedRetrievalQueryList,
    WriteListToDB,
    date_service,
)
from testgen.common.database.database_service import empty_cache

from .run_execute_cat_tests import run_cat_test_queries
from .run_refresh_data_chars import run_refresh_data_chars_queries
from .run_test_parameter_validation import run_parameter_validation_queries

LOG = logging.getLogger("testgen")


def run_test_queries(dctParms, strTestRunID, strTestTime, strProjectCode, strTestSuite, minutes_offset=0, spinner=None):
    booErrors = False
    error_msg = ""

    LOG.info("CurrentStep: Initializing Query Generator")

    clsExecute = CTestExecutionSQL(strProjectCode, dctParms["sql_flavor"], dctParms["test_suite_id"], strTestSuite, minutes_offset)
    clsExecute.run_date = strTestTime
    clsExecute.test_run_id = strTestRunID
    clsExecute.process_id = process_service.get_current_process_id()
    booClean = False

    # Add a record in Test Run table for the new Test Run
    strTestRunQuery = clsExecute.AddTestRecordtoTestRunTable()
    lstTestRunQuery = [strTestRunQuery]
    RunActionQueryList("DKTG", lstTestRunQuery)

    try:
        # Retrieve non-CAT Queries
        LOG.info("CurrentStep: Retrieve Non-CAT Queries")
        strQuery = clsExecute.GetTestsNonCAT(booClean)
        lstTestSet = RetrieveDBResultsToDictList("DKTG", strQuery)

        if len(lstTestSet) == 0:
            LOG.debug("0 non-CAT Queries retrieved.")

        if lstTestSet:
            LOG.info("CurrentStep: Preparing Non-CAT Tests")
            lstTestQueries = []
            for dctTest in lstTestSet:
                # Set Test Parms
                clsExecute.ClearTestParms()
                clsExecute.dctTestParms = dctTest
                lstTestQueries.append(clsExecute.GetTestQuery(booClean))
                if spinner:
                    spinner.next()

            # Execute list, returning test results
            LOG.info("CurrentStep: Executing Non-CAT Test Queries")
            lstTestResults, colResultNames, intErrors = RunThreadedRetrievalQueryList(
                "PROJECT", lstTestQueries, dctParms["max_threads"], spinner
            )

            # Copy test results to DK DB
            LOG.info("CurrentStep: Saving Non-CAT Test Results")
            if lstTestResults:
                WriteListToDB("DKTG", lstTestResults, colResultNames, "test_results")
            if intErrors > 0:
                booErrors = True
                error_msg = (
                    f"Errors were encountered executing Referential Tests. ({intErrors} errors occurred.) "
                    "Please check log. "
                )
                LOG.warning(error_msg)
        else:
            LOG.info("No tests found")

    except Exception as e:
        sqlsplit = e.args[0].split("[SQL", 1)
        errorline = sqlsplit[0].replace("'", "''") if len(sqlsplit) > 0 else "unknown error"
        clsExecute.exception_message = f"{type(e).__name__}: {errorline}"
        LOG.info("Updating the test run record with exception message")
        lstTestRunQuery = [clsExecute.PushTestRunStatusUpdateSQL()]
        RunActionQueryList("DKTG", lstTestRunQuery)
        raise

    else:
        return booErrors, error_msg


def run_execution_steps_in_background(project_code, test_suite):
    msg = f"Starting run_execution_steps_in_background against test suite: {test_suite}"
    if settings.IS_DEBUG:
        LOG.info(msg + ". Running in debug mode (new thread instead of new process).")
        empty_cache()
        background_thread = threading.Thread(
            target=run_execution_steps,
            args=(
                project_code,
                test_suite
            ),
        )
        background_thread.start()
    else:
        LOG.info(msg)
        script = ["testgen", "run-tests", "--project-key", project_code, "--test-suite-key", test_suite]
        subprocess.Popen(script)  # NOQA S603


def run_execution_steps(project_code: str, test_suite: str, minutes_offset: int=0, spinner: Spinner=None) -> str:
    # Initialize required parms for all steps
    has_errors = False
    error_msg = ""

    test_run_id = str(uuid.uuid4())
    test_time = date_service.get_now_as_string_with_offset(minutes_offset)

    if spinner:
        spinner.next()

    LOG.info("CurrentStep: Retrieving TestExec Parameters")
    test_exec_params = RetrieveTestExecParms(project_code, test_suite)

    LOG.info("CurrentStep: Assigning Connection Parms")
    AssignConnectParms(
        test_exec_params["project_code"],
        test_exec_params["connection_id"],
        test_exec_params["project_host"],
        test_exec_params["project_port"],
        test_exec_params["project_db"],
        test_exec_params["table_group_schema"],
        test_exec_params["project_user"],
        test_exec_params["sql_flavor"],
        test_exec_params["url"],
        test_exec_params["connect_by_url"],
        test_exec_params["connect_by_key"],
        test_exec_params["private_key"],
        test_exec_params["private_key_passphrase"],
        test_exec_params["http_path"],
        "PROJECT",
    )

    try:
        LOG.info("CurrentStep: Execute Step - Data Characteristics Refresh")
        run_refresh_data_chars_queries(test_exec_params, test_time, spinner)
    except Exception:
        LOG.warning("Data Characteristics Refresh failed", exc_info=True, stack_info=True)
        pass

    LOG.info("CurrentStep: Execute Step - Test Validation")
    run_parameter_validation_queries(test_exec_params, test_run_id, test_time, test_suite)

    LOG.info("CurrentStep: Execute Step - Test Execution")
    has_errors, error_msg = run_test_queries(
        test_exec_params, test_run_id, test_time, project_code, test_suite, minutes_offset, spinner
    )

    LOG.info("CurrentStep: Execute Step - CAT Test Execution")
    if run_cat_test_queries(
        test_exec_params, test_run_id, test_time, project_code, test_suite, error_msg, minutes_offset, spinner
    ):
        has_errors = True

    if has_errors:
        error_status = "with errors. Check log for details."
    else:
        error_status = "successfully."
    message = f"Test Execution completed {error_status}"
    return message
