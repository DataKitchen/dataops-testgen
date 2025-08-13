import logging
from collections import defaultdict
from itertools import chain

from testgen.commands.queries.test_parameter_validation_query import CTestParamValidationSQL
from testgen.common import (
    execute_db_queries,
    fetch_dict_from_db,
    fetch_list_from_db,
)
from testgen.common.get_pipeline_parms import TestExecutionParams

LOG = logging.getLogger("testgen")


def run_parameter_validation_queries(
    params: TestExecutionParams,
    test_run_id: str = "",
    test_time: str = "",
    test_suite: str = "",
):
    LOG.info("CurrentStep: Initializing Test Parameter Validation")
    clsExecute = CTestParamValidationSQL(params["sql_flavor"], params["test_suite_id"])
    clsExecute.run_date = test_time
    clsExecute.test_run_id = test_run_id
    LOG.info("CurrentStep: Validation Class successfully initialized")

    # Retrieve Test Column list
    LOG.info("CurrentStep: Retrieve Test Columns for Validation")
    test_columns, _ = fetch_list_from_db(*clsExecute.GetTestValidationColumns())

    invalid_tests = [ test_ids for col, test_ids in test_columns if not col ]
    invalid_tests = { item for sublist in invalid_tests for item in sublist }
    test_columns = [ item for item in test_columns if item[0] ]

    if not test_columns:
        LOG.warning(f"No test columns are present to validate in Test Suite {test_suite}")
        missing_columns = []
        missing_tables = set()
    else:
        # Derive test schema list -- make CSV string from list of columns
        #  to be used as criteria for retrieving data dictionary
        setSchemas = {col.split(".")[0] for col, _ in test_columns}
        strSchemas = ", ".join([f"'{value}'" for value in setSchemas])

        # Retrieve Current Project Column list
        LOG.info("CurrentStep: Retrieve Current Columns for Validation")
        clsExecute.test_schemas = strSchemas
        lstProjectTestColumns = fetch_dict_from_db(*clsExecute.GetProjectTestValidationColumns(), use_target_db=True)

        if len(lstProjectTestColumns) == 0:
            LOG.info("Current Test Column list is empty")

        LOG.info("CurrentStep: Compare column sets")
        # load results into sets
        result_set1 = {col.lower() for col, _ in test_columns}
        result_set2 = {item["columns"].lower() for item in set(lstProjectTestColumns)}

        # Check if all columns exist in the table
        missing_columns = result_set1.difference(result_set2)
        missing_columns = [ col for col in missing_columns if col.rsplit(".", 1)[1] ]
        if missing_columns:
            LOG.info("Missing columns: %s", ", ".join(missing_columns))

        # Extracting schema.tables that are missing from the result sets
        tables_set1 = {elem.rsplit(".", 1)[0] for elem in result_set1}
        tables_set2 = {elem.rsplit(".", 1)[0] for elem in result_set2}

        # Check if all the tables exist in the schema
        missing_tables = tables_set1.difference(tables_set2)

        if missing_tables:
            LOG.info("Missing tables: %s", ", ".join(missing_tables))

    if missing_columns or missing_tables or invalid_tests:
        # Flag test_definitions tests with missing tables or columns
        LOG.info("CurrentStep: Flagging Tests That Failed Validation")

        tests_missing_tables = defaultdict(list)
        tests_missing_columns = defaultdict(list)
        for column_name, test_ids in test_columns:
            column_name = column_name.lower()
            table_name = column_name.rsplit(".", 1)[0]
            if table_name in missing_tables:
                tests_missing_tables[table_name].extend(test_ids)
            elif column_name in missing_columns:
                tests_missing_columns[column_name].extend(test_ids)

        clsExecute.flag_val = "D"
        clsExecute.test_ids = list(set(chain(*tests_missing_tables.values(), *tests_missing_columns.values(), invalid_tests)))
        execute_db_queries([clsExecute.PrepFlagTestsWithFailedValidation()])

        for column_name, test_ids in tests_missing_columns.items():
            clsExecute.message = f"Missing column: {column_name}"
            clsExecute.test_ids = test_ids
            execute_db_queries([clsExecute.FlagTestsWithFailedValidation()])

        for table_name, test_ids in tests_missing_tables.items():
            clsExecute.message = f"Missing table: {table_name}"
            clsExecute.test_ids = test_ids
            execute_db_queries([clsExecute.FlagTestsWithFailedValidation()])
        
        if invalid_tests:
            clsExecute.message = "Invalid test: schema, table, or column not defined"
            clsExecute.test_ids = invalid_tests
            execute_db_queries([clsExecute.FlagTestsWithFailedValidation()])

        # Copy test results to DK DB, using temporary flagged D value to identify
        LOG.info("CurrentStep: Saving error results for invalid tests")
        execute_db_queries([clsExecute.ReportTestValidationErrors()])

        # Set to Inactive those test_definitions tests that are flagged D:  set to N
        LOG.info("CurrentStep: Disabling Tests That Failed Validation")
        execute_db_queries([clsExecute.DisableTestsWithFailedValidation()])

        LOG.info("Validation Complete: Tests referencing missing tables or columns have been deactivated.")
    else:
        LOG.info("Validation Successful: No tables or columns missing from target database.")
