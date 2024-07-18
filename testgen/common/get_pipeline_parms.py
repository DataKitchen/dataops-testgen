from testgen.common.database.database_service import RetrieveDBResultsToDictList
from testgen.common.read_file import read_template_sql_file


def RetrieveProfilingParms(strTableGroupsID):
    strSQL = read_template_sql_file("parms_profiling.sql", "parms")
    # Replace Parameters
    strSQL = strSQL.replace("{TABLE_GROUPS_ID}", strTableGroupsID)

    # Execute Query
    lstParms = RetrieveDBResultsToDictList("DKTG", strSQL)

    if lstParms is None:
        raise ValueError("Project Connection Parameters not found")
    elif (
        lstParms[0]["project_code"] == ""
        or lstParms[0]["connection_id"] == ""
        or lstParms[0]["sql_flavor"] == ""
        or lstParms[0]["project_user"] == ""
        or lstParms[0]["profile_use_sampling"] == ""
        or lstParms[0]["profile_sample_percent"] == ""
        or lstParms[0]["profile_sample_min_count"] == ""
        or lstParms[0]["project_qc_schema"] == ""
        or lstParms[0]["table_group_schema"] == ""
    ):
        raise ValueError("Project Connection parameters not correctly set")
    else:
        return lstParms[0]


def RetrieveTestGenParms(strTableGroupsID, strTestSuite):
    strSQL = read_template_sql_file("parms_test_gen.sql", "parms")
    # Replace Parameters
    strSQL = strSQL.replace("{TABLE_GROUPS_ID}", strTableGroupsID)
    strSQL = strSQL.replace("{TEST_SUITE}", strTestSuite)

    # Execute Query
    lstParms = RetrieveDBResultsToDictList("DKTG", strSQL)
    if len(lstParms) == 0:
        raise ValueError("SQL retrieved 0 records")
    return lstParms[0]


def RetrieveTestExecParms(strProjectCode, strTestSuite):
    strSQL = read_template_sql_file("parms_test_execution.sql", "parms")
    # Replace Parameters
    strSQL = strSQL.replace("{PROJECT_CODE}", strProjectCode)
    strSQL = strSQL.replace("{TEST_SUITE}", strTestSuite)

    # Execute Query
    lstParms = RetrieveDBResultsToDictList("DKTG", strSQL)
    if len(lstParms) == 0:
        raise ValueError("Test Execution parameters could not be retrieved")
    elif len(lstParms) > 1:
        raise ValueError("Test Execution parameters returned too many records")

    return lstParms[0]
