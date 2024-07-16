import logging
import typing

from testgen.common import CleanSQL, date_service, get_template_files, read_template_sql_file

LOG = logging.getLogger("testgen")


class CDeriveTestsSQL:
    run_date = ""
    project_code = ""
    connection_id = ""
    table_groups_id = ""
    data_schema = ""
    test_suite = ""
    test_suite_id = ""
    generation_set = ""
    as_of_date = ""
    sql_flavor = ""
    dctTestParms: typing.ClassVar = {}

    def __init__(self):
        today = date_service.get_now_as_string()
        self.run_date = today
        self.as_of_date = today
        self.dctTestParms = {}

    def ClearTestParms(self):
        # Test Set Parameters
        self.dctTestParms = {}

    def ReplaceParms(self, strInputString):
        for parm, value in self.dctTestParms.items():
            strInputString = strInputString.replace("{" + parm.upper() + "}", value)

        strInputString = strInputString.replace("{PROJECT_CODE}", self.project_code)
        strInputString = strInputString.replace("{SQL_FLAVOR}", self.sql_flavor)
        strInputString = strInputString.replace("{CONNECTION_ID}", self.connection_id)
        strInputString = strInputString.replace("{TABLE_GROUPS_ID}", self.table_groups_id)
        strInputString = strInputString.replace("{RUN_DATE}", self.run_date)
        strInputString = strInputString.replace("{TEST_SUITE}", self.test_suite)
        strInputString = strInputString.replace("{TEST_SUITE_ID}", self.test_suite_id)
        strInputString = strInputString.replace("{GENERATION_SET}", self.generation_set)
        strInputString = strInputString.replace("{AS_OF_DATE}", self.as_of_date)
        strInputString = strInputString.replace("{DATA_SCHEMA}", self.data_schema)

        return strInputString

    def GetInsertTestSuiteSQL(self, booClean):
        strQuery = self.ReplaceParms(read_template_sql_file("gen_insert_test_suite.sql", "generation"))
        if booClean:
            strQuery = CleanSQL(strQuery)

        return strQuery

    def GetTestTypesSQL(self, booClean):
        strQuery = self.ReplaceParms(read_template_sql_file("gen_standard_test_type_list.sql", "generation"))
        if booClean:
            strQuery = CleanSQL(strQuery)

        return strQuery

    def GetTestDerivationQueriesAsList(self, booClean):
        # This assumes the queries run in no particular order,
        # and will order them alphabetically by file name
        lstQueries = sorted(
            get_template_files(mask=r"^.*sql$", sub_directory="gen_funny_cat_tests"), key=lambda key: str(key)
        )
        lstTemplate = []

        for script in lstQueries:
            query = script.read_text("utf-8")
            template = self.ReplaceParms(query)
            lstTemplate.append(template)

        if booClean:
            lstTemplate = [CleanSQL(q) for q in lstTemplate]

        if len(lstQueries) == 0:
            LOG.warning("No funny CAT test generation templates were found")

        return lstTemplate

    def GetTestQueriesFromGenericFile(self, booClean: bool):
        strQuery = self.ReplaceParms(read_template_sql_file("gen_standard_tests.sql", "generation"))
        if booClean:
            strQuery = CleanSQL(strQuery)
        return strQuery

    def GetDeleteOldTestsQuery(self, booClean: bool):
        strQuery = self.ReplaceParms(read_template_sql_file("gen_delete_old_tests.sql", "generation"))
        if booClean:
            strQuery = CleanSQL(strQuery)
        return strQuery
