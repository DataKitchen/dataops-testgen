import logging

from testgen.commands.queries.generate_tests_query import CDeriveTestsSQL
from testgen.common import AssignConnectParms, RetrieveDBResultsToDictList, RetrieveTestGenParms, RunActionQueryList

LOG = logging.getLogger("testgen")


def run_test_gen_queries(strTableGroupsID, strTestSuite, strGenerationSet=None):
    if strTableGroupsID is None:
        raise ValueError("Table Group ID was not specified")

    clsTests = CDeriveTestsSQL()

    # Set General Parms
    booClean = False

    LOG.info("CurrentStep: Retrieving General Parameters for Test Suite %s", strTestSuite)
    dctParms = RetrieveTestGenParms(strTableGroupsID, strTestSuite)

    # Set Project Connection Parms from retrieved parms
    LOG.info("CurrentStep: Assigning Connection Parameters")
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

    # Set static parms
    clsTests.project_code = dctParms["project_code"]
    clsTests.test_suite = strTestSuite
    clsTests.generation_set = strGenerationSet if strGenerationSet is not None else ""
    clsTests.test_suite_id = dctParms["test_suite_id"] if dctParms["test_suite_id"] else ""
    clsTests.connection_id = str(dctParms["connection_id"])
    clsTests.table_groups_id = strTableGroupsID
    clsTests.sql_flavor = dctParms["sql_flavor"]
    clsTests.data_schema = dctParms["table_group_schema"]
    if dctParms["profiling_as_of_date"] is not None:
        clsTests.as_of_date = dctParms["profiling_as_of_date"].strftime("%Y-%m-%d %H:%M:%S")

    if dctParms["test_suite_id"]:
        clsTests.test_suite_id = dctParms["test_suite_id"]
    else:
        LOG.info("CurrentStep: Creating new Test Suite")
        strQuery = clsTests.GetInsertTestSuiteSQL(booClean)
        if strQuery:
            clsTests.test_suite_id, = RunActionQueryList("DKTG", [strQuery])
        else:
            raise ValueError("Test Suite not found and could not be created")

    LOG.info("CurrentStep: Compiling Test Gen Queries")

    lstFunnyTemplateQueries = clsTests.GetTestDerivationQueriesAsList(booClean)
    lstGenericTemplateQueries = []

    # Delete old Tests
    strDeleteQuery = clsTests.GetDeleteOldTestsQuery(booClean)

    # Retrieve test_types as parms from list of dictionaries:  test_type, selection_criteria, default_parm_columns,
    # default_parm_values
    strQuery = clsTests.GetTestTypesSQL(booClean)

    # Execute Query
    if strQuery:
        lstTestTypes = RetrieveDBResultsToDictList("DKTG", strQuery)

        if lstTestTypes is None:
            raise ValueError("Test Type Parameters not found")
        elif (
            lstTestTypes[0]["test_type"] == ""
            or lstTestTypes[0]["selection_criteria"] == ""
            or lstTestTypes[0]["default_parm_columns"] == ""
            or lstTestTypes[0]["default_parm_values"] == ""
        ):
            raise ValueError("Test Type parameters not correctly set")
    else:
        raise ValueError("Test Type Queries were not generated")

    for dctTestParms in lstTestTypes:
        clsTests.ClearTestParms()
        clsTests.dctTestParms = dctTestParms
        strQuery = clsTests.GetTestQueriesFromGenericFile(booClean)

        if strQuery:
            lstGenericTemplateQueries.append(strQuery)

    LOG.info("TestGen CAT Queries were compiled")

    # Make sure delete, then generic templates run before the funny templates
    lstQueries = [strDeleteQuery, *lstGenericTemplateQueries, *lstFunnyTemplateQueries]

    if lstQueries:
        LOG.info("Running Test Generation Template Queries")
        RunActionQueryList("DKTG", lstQueries)
        return "Test generation completed successfully."
    else:
        return "No TestGen Queries were compiled."
