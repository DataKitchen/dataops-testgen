import logging

from testgen.commands.queries.test_parameter_validation_query import CTestParamValidationSQL
from testgen.common import AssignConnectParms, RetrieveDBResultsToDictList, RetrieveTestExecParms, RunActionQueryList

LOG = logging.getLogger("testgen")


def run_parameter_validation_queries(
    test_run_id="", test_time="", strProjectCode="", strTestSuite="", booRunFromTestExec=True
):
    LOG.info("CurrentStep: Retrieving TestzVal Parameters")
    dctParms = RetrieveTestExecParms(strProjectCode, strTestSuite)
    LOG.debug("Test Parameter Validation - Parameters retrieved")

    # Set Project Connection Parms in db_bridgers from retrieved parms
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

    LOG.debug("Validating parameters for Test Suite %s")

    LOG.info("CurrentStep: Initializing Test Parameter Validation")
    clsExecute = CTestParamValidationSQL(strProjectCode, dctParms["sql_flavor"], strTestSuite)
    clsExecute.run_date = test_time
    clsExecute.test_run_id = test_run_id
    LOG.info("CurrentStep: Validation Class successfully initialized")

    booClean = False

    # Retrieve Test Column list
    LOG.info("CurrentStep: Retrieve Test Columns for Validation")
    strColumnList = clsExecute.GetTestValidationColumns(booClean)
    lstTestColumns = RetrieveDBResultsToDictList("DKTG", strColumnList)

    if len(lstTestColumns) == 0:
        LOG.warning(f"No test columns are present to validate in Test Suite {strTestSuite}")
        missing_columns = []
    else:
        # Derive test schema list -- make CSV string from list of columns
        #  to be used as criteria for retrieving data dictionary
        setSchemas = {s["columns"].split(".")[0] for s in lstTestColumns}
        strSchemas = ", ".join([f"'{value}'" for value in setSchemas])
        LOG.debug("Test column list successfully retrieved")

        # Retrieve Project Column list
        LOG.info("CurrentStep: Retrieve Test Columns for Validation")
        clsExecute.test_schemas = strSchemas
        strProjectColumnList = clsExecute.GetProjectTestValidationColumns()
        if "where table_schema in ()" in strProjectColumnList:
            raise ValueError("No schema specified in Validation Columns check")
        lstProjectTestColumns = RetrieveDBResultsToDictList("PROJECT", strProjectColumnList)

        if len(lstProjectTestColumns) == 0:
            LOG.info("Project Test Column list is empty")

        LOG.debug("Project column list successfully received")
        LOG.info("CurrentStep: Compare column sets")
        # load results into sets
        result_set1 = {item["columns"].lower() for item in set(lstTestColumns)}
        result_set2 = {item["columns"].lower() for item in set(lstProjectTestColumns)}

        # Check if all columns exist in the table
        missing_columns = result_set1.difference(result_set2)

        if len(missing_columns) == 0:
            LOG.info("No missing column in Project Column list.")

        strMissingColumns = ", ".join(f"'{x}'" for x in missing_columns)
        srtNoQuoteMissingCols = strMissingColumns.replace("'", "")

    if missing_columns:
        LOG.debug("Test Columns are missing in target database: %s", srtNoQuoteMissingCols)

        # Extracting schema.tables that are missing from the result sets
        tables_set1 = {elem.rsplit(".", 1)[0] for elem in result_set1}
        tables_set2 = {elem.rsplit(".", 1)[0] for elem in result_set2}

        # Check if all the tables exist in the schema
        missing_tables = tables_set1.difference(tables_set2)

        if missing_tables:
            strMissingtables = ", ".join(f"'{x}'" for x in missing_tables)
        else:
            LOG.info("No missing tables in Project Column list.")
            strMissingtables = "''"

        # Flag test_definitions tests with missing columns:
        LOG.info("CurrentStep: Flagging Tests That Failed Validation")
        clsExecute.missing_columns = strMissingColumns
        clsExecute.missing_tables = strMissingtables
        # Flag Value is D if called from execute_tests_qry.py, otherwise N to disable now
        if booRunFromTestExec:
            clsExecute.flag_val = "D"
            strTempMessage = "Tests that failed parameter validation have been flagged."
        else:
            clsExecute.flag_val = "N"
            strTempMessage = "Tests that failed parameter validation have been set to inactive."
        strFlagTests = clsExecute.FlagTestsWithFailedValidation()
        RunActionQueryList("DKTG", [strFlagTests])
        LOG.debug(strTempMessage)

        # when run_parameter_validation_queries() is called from execute_tests_query.py:
        # we disable tests and write validation errors to test_results table.
        if booRunFromTestExec:
            # Copy test results to DK DB, using temporary flagged -1 value to identify
            LOG.info("CurrentStep: Saving error results for invalid tests")
            strReportValErrors = clsExecute.ReportTestValidationErrors()
            RunActionQueryList("DKTG", [strReportValErrors])
            LOG.debug("Results inserted for invalid tests")

            # Set to Inactive those test_definitions tests that are flagged D:  set to N

            LOG.info("CurrentStep: Disabling Tests That Failed Validation")
            strDisableTests = clsExecute.DisableTestsWithFailedValidation()
            RunActionQueryList("DKTG", [strDisableTests])
            LOG.debug("Tests that failed parameter validation have been disabled.")

        LOG.info("Validation Complete: tests referencing missing columns have been disabled.")
    else:
        LOG.info("Validation Successful: No columns missing from target database.")
