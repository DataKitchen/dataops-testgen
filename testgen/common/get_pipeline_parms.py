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

    required_params = (
        "project_code",
        "connection_id",
        "sql_flavor",
        "project_user",
        "profile_use_sampling",
        "profile_sample_percent",
        "profile_sample_min_count",
        "table_group_schema",
    )

    if missing := [param for param in required_params if not lstParms[0][param]]:
        raise ValueError(f"Project Connection parameters are missing: {', '.join(missing)}.")

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
