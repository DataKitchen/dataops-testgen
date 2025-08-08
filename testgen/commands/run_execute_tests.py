import logging
import subprocess
import threading
import uuid

from progress.spinner import Spinner

import testgen.common.process_service as process_service
from testgen import settings
from testgen.commands.queries.execute_tests_query import CTestExecutionSQL
from testgen.common import (
    date_service,
    execute_db_queries,
    fetch_dict_from_db,
    fetch_from_db_threaded,
    get_test_execution_params,
    set_target_db_params,
    write_to_app_db,
)
from testgen.common.database.database_service import empty_cache
from testgen.common.get_pipeline_parms import TestExecutionParams
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.ui.session import session

from .run_execute_cat_tests import run_cat_test_queries
from .run_refresh_data_chars import run_refresh_data_chars_queries
from .run_test_parameter_validation import run_parameter_validation_queries

LOG = logging.getLogger("testgen")


def add_test_run_record(test_run_id: str, test_suite_id: str, test_time: str, process_id: int):
    execute_db_queries([(
        """
        INSERT INTO test_runs(id, test_suite_id, test_starttime, process_id)
        (SELECT :test_run_id as id,
                :test_suite_id as test_suite_id,
                :test_time as test_starttime,
                :process_id as process_id);
        """,
        {
            "test_run_id": test_run_id,
            "test_suite_id": test_suite_id,
            "test_time": test_time,
            "process_id": process_id,
        }
    )])


def run_test_queries(
    params: TestExecutionParams,
    test_run_id: str,
    test_time: str,
    project_code: str,
    test_suite: str,
    minutes_offset: int = 0,
    spinner: Spinner | None = None,
):
    has_errors = False
    error_msg = ""

    LOG.info("CurrentStep: Initializing Query Generator")

    clsExecute = CTestExecutionSQL(project_code, params["sql_flavor"], params["test_suite_id"], test_suite, minutes_offset)
    clsExecute.run_date = test_time
    clsExecute.test_run_id = test_run_id
    clsExecute.process_id = process_service.get_current_process_id()

    try:
        # Retrieve non-CAT Queries
        LOG.info("CurrentStep: Retrieve Non-CAT Queries")
        lstTestSet = fetch_dict_from_db(*clsExecute.GetTestsNonCAT())

        if len(lstTestSet) == 0:
            LOG.debug("0 non-CAT Queries retrieved.")

        if lstTestSet:
            LOG.info("CurrentStep: Preparing Non-CAT Tests")
            lstTestQueries = []
            for dctTest in lstTestSet:
                clsExecute.test_params = dctTest
                lstTestQueries.append(clsExecute.GetTestQuery())
                if spinner:
                    spinner.next()

            # Execute list, returning test results
            LOG.info("CurrentStep: Executing Non-CAT Test Queries")
            lstTestResults, colResultNames, intErrors = fetch_from_db_threaded(
                lstTestQueries, use_target_db=True, max_threads=params["max_threads"], spinner=spinner
            )

            # Copy test results to DK DB
            LOG.info("CurrentStep: Saving Non-CAT Test Results")
            if lstTestResults:
                write_to_app_db(lstTestResults, colResultNames, "test_results")
            if intErrors > 0:
                has_errors = True
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
        execute_db_queries([clsExecute.PushTestRunStatusUpdateSQL()])
        raise

    else:
        return has_errors, error_msg


def run_execution_steps_in_background(project_code, test_suite):
    msg = f"Starting run_execution_steps_in_background against test suite: {test_suite}"
    if settings.IS_DEBUG:
        LOG.info(msg + ". Running in debug mode (new thread instead of new process).")
        empty_cache()
        background_thread = threading.Thread(
            target=run_execution_steps,
            args=(project_code, test_suite, session.username),
        )
        background_thread.start()
    else:
        LOG.info(msg)
        script = ["testgen", "run-tests", "--project-key", project_code, "--test-suite-key", test_suite]
        subprocess.Popen(script)  # NOQA S603


@with_database_session
def run_execution_steps(
    project_code: str,
    test_suite: str,
    username: str | None = None,
    minutes_offset: int = 0,
    spinner: Spinner | None = None,
) -> str:
    # Initialize required parms for all steps
    has_errors = False
    error_msg = ""

    test_run_id = str(uuid.uuid4())
    test_time = date_service.get_now_as_string_with_offset(minutes_offset)

    if spinner:
        spinner.next()

    LOG.info("CurrentStep: Retrieving TestExec Parameters")
    test_exec_params = get_test_execution_params(project_code, test_suite)

    # Add a record in Test Run table for the new Test Run
    add_test_run_record(
        test_run_id, test_exec_params["test_suite_id"], test_time, process_service.get_current_process_id()
    )

    LOG.info("CurrentStep: Assigning Connection Parameters")
    connection = Connection.get_by_table_group(test_exec_params["table_groups_id"])
    set_target_db_params(connection.__dict__)
    test_exec_params["sql_flavor"] = connection.sql_flavor
    test_exec_params["max_query_chars"] = connection.max_query_chars
    test_exec_params["max_threads"] = connection.max_threads

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
        test_exec_params, test_run_id, test_time, project_code, test_suite, error_msg, username, minutes_offset, spinner
    ):
        has_errors = True

    return f"""
        Test execution completed {"with errors. Check log for details." if has_errors else "successfully."}
        Run ID: {test_run_id}
    """
