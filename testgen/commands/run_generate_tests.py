import logging

from testgen import settings
from testgen.commands.queries.generate_tests_query import CDeriveTestsSQL
from testgen.common import execute_db_queries, fetch_dict_from_db, get_test_generation_params, set_target_db_params
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection

LOG = logging.getLogger("testgen")


@with_database_session
def run_test_gen_queries(table_group_id: str, test_suite: str, generation_set: str | None = None):
    if table_group_id is None:
        raise ValueError("Table Group ID was not specified")

    LOG.info("CurrentStep: Assigning Connection Parameters")
    connection = Connection.get_by_table_group(table_group_id)
    set_target_db_params(connection.__dict__)

    clsTests = CDeriveTestsSQL()

    LOG.info(f"CurrentStep: Retrieving General Parameters for Test Suite {test_suite}")
    params = get_test_generation_params(table_group_id, test_suite)


    # Set static parms
    clsTests.project_code = params["project_code"]
    clsTests.test_suite = test_suite
    clsTests.generation_set = generation_set if generation_set is not None else ""
    clsTests.test_suite_id = params["test_suite_id"] if params["test_suite_id"] else ""
    clsTests.connection_id = str(connection.connection_id)
    clsTests.table_groups_id = table_group_id
    clsTests.sql_flavor = connection.sql_flavor
    clsTests.data_schema = params["table_group_schema"]
    if params["profiling_as_of_date"] is not None:
        clsTests.as_of_date = params["profiling_as_of_date"].strftime("%Y-%m-%d %H:%M:%S")

    if params["test_suite_id"]:
        clsTests.test_suite_id = params["test_suite_id"]
    else:
        LOG.info("CurrentStep: Creating new Test Suite")
        insert_ids, _ = execute_db_queries([clsTests.GetInsertTestSuiteSQL()])
        clsTests.test_suite_id = insert_ids[0]

    LOG.info("CurrentStep: Compiling Test Gen Queries")

    lstFunnyTemplateQueries = clsTests.GetTestDerivationQueriesAsList("gen_funny_cat_tests")
    lstQueryTemplateQueries = clsTests.GetTestDerivationQueriesAsList("gen_query_tests")
    lstGenericTemplateQueries = []

    # Delete old Tests
    deleteQuery = clsTests.GetDeleteOldTestsQuery()

    # Retrieve test_types as parms from list of dictionaries:  test_type, selection_criteria, default_parm_columns,
    # default_parm_values
    lstTestTypes = fetch_dict_from_db(*clsTests.GetTestTypesSQL())

    if lstTestTypes is None:
        raise ValueError("Test Type Parameters not found")
    elif (
        lstTestTypes[0]["test_type"] == ""
        or lstTestTypes[0]["selection_criteria"] == ""
        or lstTestTypes[0]["default_parm_columns"] == ""
        or lstTestTypes[0]["default_parm_values"] == ""
    ):
        raise ValueError("Test Type parameters not correctly set")

    lstGenericTemplateQueries = []
    for dctTestParms in lstTestTypes:
        clsTests.gen_test_params = dctTestParms
        lstGenericTemplateQueries.append(clsTests.GetTestQueriesFromGenericFile())

    LOG.info("TestGen CAT Queries were compiled")

    # Make sure delete, then generic templates run before the funny templates
    lstQueries = [deleteQuery, *lstGenericTemplateQueries, *lstFunnyTemplateQueries, *lstQueryTemplateQueries]

    if lstQueries:
        LOG.info("Running Test Generation Template Queries")
        execute_db_queries(lstQueries)
        message = "Test generation completed successfully."
    else:
        message = "No TestGen Queries were compiled."

    MixpanelService().send_event(
        "generate-tests",
        source=settings.ANALYTICS_JOB_SOURCE,
        sql_flavor=clsTests.sql_flavor,
        generation_set=clsTests.generation_set,
    )

    return message
