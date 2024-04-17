from testgen.common import RetrieveDBResultsToDictList, RunActionQueryList, WriteListToDB, read_template_sql_file


def get_test_def_parms(project_code, test_suite):
    lstResults = run_test_def_parms(project_code, test_suite)

    if lstResults is None:
        raise ValueError("Test Definition Parameters not found")

    yaml_dict = {}

    for row in lstResults:
        project_code = row["project_code"]
        test_suite = row["test_suite"]
        schema = row["schema_name"]
        table_name = row["table_name"]
        column_name = row["column_name"]
        row_id = (row["id"],)
        test_type = (row["test_type"],)
        test_description = (row["test_description"],)
        test_action = (row["test_action"],)
        test_active = (row["test_active"],)
        lock_refresh = (row["lock_refresh"],)
        severity = (row["severity"],)
        test_parameters = (row["test_parameters"],)

        if project_code not in yaml_dict:
            yaml_dict[project_code] = {}
        if test_suite not in yaml_dict[project_code]:
            yaml_dict[project_code][test_suite] = {}
        if schema not in yaml_dict[project_code][test_suite]:
            yaml_dict[project_code][test_suite][schema] = {}
        if table_name not in yaml_dict[project_code][test_suite][schema]:
            yaml_dict[project_code][test_suite][schema][table_name] = {}
        if column_name not in yaml_dict[project_code][test_suite][schema][table_name]:
            yaml_dict[project_code][test_suite][schema][table_name][column_name] = []

        parm_columns = test_parameters[0].split(",")
        parm_dict = {}

        for column in parm_columns:
            parm_dict[column] = row[column]

        yaml_dict[project_code][test_suite][schema][table_name][column_name].append(
            {
                "id": str(row_id[0]),
                "test_type": str(test_type[0]),
                "test_description": str(test_description[0]),
                "test_action": str(test_action[0]),
                "test_active": str(test_active[0]),
                "lock_refresh": str(lock_refresh[0]),
                "severity": str(severity[0]),
                "test_parameters": parm_dict,
            }
        )

    return yaml_dict


def run_test_def_parms(project_code, test_suite):
    sql_template = read_template_sql_file("get_test_def_parms.sql", "updates")

    sql_template = sql_template.replace("{PROJECT_CODE}", project_code)
    sql_template = sql_template.replace("{TEST_SUITE}", test_suite)

    return RetrieveDBResultsToDictList("DKTG", sql_template)


def update_test_def_parms_dict(yaml_dict):
    if yaml_dict is None:
        raise ValueError("Test Definition Parameters not found")

    updResults = update_test_definitions(yaml_dict)
    RunActionQueryList("DKTG", updResults)


def update_test_definitions(data):
    list_columns = []
    list_update_insert_queries = []

    for project_code, test_suite_dict in data.items():
        for test_suite, schema_dict in test_suite_dict.items():
            for schema, table_dict in schema_dict.items():
                for table, column_dict in table_dict.items():
                    for column, attributes_list in column_dict.items():
                        for attribute in attributes_list:
                            id_col = attribute["id"]
                            test_type = attribute["test_type"]
                            test_description = attribute["test_description"]
                            test_action = attribute["test_action"]
                            test_active = attribute["test_active"]
                            lock_refresh = attribute["lock_refresh"]
                            severity = attribute["severity"]
                            test_parameters = attribute["test_parameters"]

                            column_keys = test_parameters.keys()
                            column_values = test_parameters.values()

                            for col, value in zip(column_keys, column_values, strict=False):
                                list_columns.append(
                                    [
                                        project_code,
                                        test_suite,
                                        schema,
                                        table,
                                        column,
                                        id_col,
                                        test_type,
                                        test_description,
                                        test_action,
                                        test_active,
                                        lock_refresh,
                                        severity,
                                        col,
                                        value,
                                    ]
                                )

    col_list = [
        "project_code",
        "test_suite",
        "schema_name",
        "table_name",
        "column_name",
        "id",
        "test_type",
        "test_description",
        "test_action",
        "test_active",
        "lock_refresh",
        "severity",
        "test_parameter",
        "test_parameter_value",
    ]

    list_create_queries = []
    create_table = read_template_sql_file("create_tmp_test_definition.sql", "updates")
    list_create_queries.append(create_table)
    RunActionQueryList("DKTG", list_create_queries)

    # Write to tmp_test_definition
    WriteListToDB("DKTG", list_columns, col_list, "tmp_test_definition")

    sql_template = read_template_sql_file("populate_stg_test_definitions.sql", "updates")
    list_update_insert_queries.append(sql_template)
    return list_update_insert_queries
