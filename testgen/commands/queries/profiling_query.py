import typing

from testgen.common import date_service, read_template_sql_file, read_template_yaml_file


class CProfilingSQL:
    template_path = ""
    dctTemplates: typing.ClassVar = {}
    dctSnippetTemplate: typing.ClassVar = {}

    project_code = ""
    connection_id = ""
    table_groups_id = ""
    flavor = ""
    run_date = ""
    data_qc_schema = ""
    data_schema = ""
    data_table = ""

    col_name = ""
    col_gen_type = ""
    col_type = ""
    col_ordinal_position = "0"

    col_max_char_length = 0
    col_is_decimal = ""
    col_top_freq_update = ""

    parm_table_set = None
    parm_table_include_mask = None
    parm_table_exclude_mask = None
    parm_do_patterns = "Y"
    parm_max_pattern_length = 30
    parm_do_freqs = "Y"
    parm_max_freq_length = 30
    parm_vldb_flag = "N"
    parm_do_sample = "N"
    parm_sample_size = ""
    profile_run_id = ""
    profile_id_column_mask = ""
    profile_sk_column_mask = ""
    profile_use_sampling = ""
    profile_sample_percent = ""
    profile_sample_min_count = ""

    sampling_table = ""
    sample_ratio = ""

    process_id = None

    contingency_max_values = "4"
    contingency_columns = ""

    exception_message = ""

    def __init__(self, strProjectCode, flavor):
        self.flavor = flavor
        self.project_code = strProjectCode
        # Defaults
        self.run_date = date_service.get_now_as_string()
        self.col_ordinal_position = "0"
        self.col_max_char_length = 0
        self.parm_do_patterns = "Y"
        self.parm_max_pattern_length = 25
        self.parm_do_freqs = "Y"
        self.parm_max_freq_length = 25
        self.parm_vldb_flag = "N"
        self.parm_do_sample = "N"
        self.today = date_service.get_now_as_string()

    def ReplaceParms(self, strInputString):
        strInputString = strInputString.replace("{PROJECT_CODE}", self.project_code)
        strInputString = strInputString.replace("{CONNECTION_ID}", self.connection_id)
        strInputString = strInputString.replace("{TABLE_GROUPS_ID}", self.table_groups_id)
        strInputString = strInputString.replace("{RUN_DATE}", self.run_date)
        strInputString = strInputString.replace("{DATA_SCHEMA}", self.data_schema)
        strInputString = strInputString.replace("{DATA_QC_SCHEMA}", self.data_qc_schema)
        strInputString = strInputString.replace("{DATA_TABLE}", self.data_table)
        strInputString = strInputString.replace("{COL_NAME}", self.col_name)
        strInputString = strInputString.replace("{COL_NAME_SANITIZED}", self.col_name.replace("'", "''"))
        strInputString = strInputString.replace("{COL_GEN_TYPE}", self.col_gen_type)
        strInputString = strInputString.replace("{COL_TYPE}", self.col_type)
        strInputString = strInputString.replace("{COL_POS}", str(self.col_ordinal_position))
        strInputString = strInputString.replace("{TOP_FREQ}", self.col_top_freq_update)
        strInputString = strInputString.replace("{PROFILE_RUN_ID}", self.profile_run_id)
        strInputString = strInputString.replace("{PROFILE_ID_COLUMN_MASK}", self.profile_id_column_mask)
        strInputString = strInputString.replace("{PROFILE_SK_COLUMN_MASK}", self.profile_sk_column_mask)
        strInputString = strInputString.replace("{START_TIME}", self.today)
        strInputString = strInputString.replace("{NOW}", date_service.get_now_as_string())
        strInputString = strInputString.replace("{EXCEPTION_MESSAGE}", self.exception_message)
        strInputString = strInputString.replace("{SAMPLING_TABLE}", self.sampling_table)
        strInputString = strInputString.replace("{SAMPLE_SIZE}", str(self.parm_sample_size))
        strInputString = strInputString.replace("{PROFILE_USE_SAMPLING}", self.profile_use_sampling)
        strInputString = strInputString.replace("{PROFILE_SAMPLE_PERCENT}", self.profile_sample_percent)
        strInputString = strInputString.replace("{PROFILE_SAMPLE_MIN_COUNT}", str(self.profile_sample_min_count))
        strInputString = strInputString.replace("{PROFILE_SAMPLE_RATIO}", str(self.sample_ratio))
        strInputString = strInputString.replace("{PARM_MAX_PATTERN_LENGTH}", str(self.parm_max_pattern_length))
        strInputString = strInputString.replace("{CONTINGENCY_COLUMNS}", self.contingency_columns)
        strInputString = strInputString.replace("{CONTINGENCY_MAX_VALUES}", self.contingency_max_values)
        strInputString = strInputString.replace("{PROCESS_ID}", str(self.process_id))

        return strInputString

    def GetSecondProfilingColumnsQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("secondary_profiling_columns.sql", sub_directory="profiling"))
        return strQ

    def GetSecondProfilingUpdateQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("secondary_profiling_update.sql", sub_directory="profiling"))
        return strQ

    def GetSecondProfilingStageDeleteQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("secondary_profiling_delete.sql", sub_directory="profiling"))
        return strQ

    def GetDataTypeSuggestionUpdateQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("datatype_suggestions.sql", sub_directory="profiling"))
        return strQ

    def GetFunctionalDataTypeUpdateQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("functional_datatype.sql", sub_directory="profiling"))
        return strQ

    def GetFunctionalTableTypeStageQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("functional_tabletype_stage.sql", sub_directory="profiling"))
        return strQ

    def GetFunctionalTableTypeUpdateQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("functional_tabletype_update.sql", sub_directory="profiling"))
        return strQ

    def GetPIIFlagUpdateQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("pii_flag.sql", sub_directory="profiling"))
        return strQ

    def GetAnomalyRefreshQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("refresh_anomalies.sql", sub_directory="profiling"))
        return strQ

    def GetAnomalyTestTypesQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(read_template_sql_file("profile_anomaly_types_get.sql", sub_directory="profiling"))
        return strQ

    def GetAnomalyTestQuery(self, dct_test_type):
        # Runs on DK Postgres Server
        strQ = None

        match dct_test_type["data_object"]:
            case "Column":
                strQ = read_template_sql_file("profile_anomalies_screen_column.sql", sub_directory="profiling")
            case "Multi-Col":
                strQ = read_template_sql_file("profile_anomalies_screen_multi_column.sql", sub_directory="profiling")
            case "Dates":
                strQ = read_template_sql_file("profile_anomalies_screen_table_dates.sql", sub_directory="profiling")
            case "Table":
                strQ = read_template_sql_file("profile_anomalies_screen_table.sql", sub_directory="profiling")
            case "Variant":
                strQ = read_template_sql_file("profile_anomalies_screen_variants.sql", sub_directory="profiling")

        if strQ:
            strQ = strQ.replace("{ANOMALY_ID}", dct_test_type["id"])
            strQ = strQ.replace("{DETAIL_EXPRESSION}", dct_test_type["detail_expression"])
            strQ = strQ.replace("{ANOMALY_CRITERIA}", dct_test_type["anomaly_criteria"])
            strQ = self.ReplaceParms(strQ)

        return strQ

    def GetDataCharsRefreshQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(
            read_template_sql_file("refresh_data_chars_from_profiling.sql", sub_directory="profiling")
        )
        return strQ

    def GetProfileRunInfoRecordsQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(
            read_template_sql_file("project_profile_run_record_insert.sql", sub_directory="profiling")
        )
        return strQ

    def GetProfileRunInfoRecordUpdateQuery(self):
        # Runs on DK Postgres Server
        strQ = self.ReplaceParms(
            read_template_sql_file("project_profile_run_record_update.sql", sub_directory="profiling")
        )
        return strQ

    def GetDDFQuery(self):
        # Runs on Project DB

        strQ = self.ReplaceParms(
            read_template_sql_file(
                f"project_ddf_query_{self.flavor}.sql", sub_directory=f"flavors/{self.flavor}/profiling"
            )
        )

        strTableCriteria = ""
        if self.parm_table_set:
            strTableCriteria += " AND c.table_name IN (" + self.parm_table_set + ")"
        strTableCriteria += self._get_mask_query(self.parm_table_include_mask, is_include=True)
        strTableCriteria += self._get_mask_query(self.parm_table_exclude_mask, is_include=False)
        strQ = strQ.replace("{TABLE_CRITERIA}", strTableCriteria)

        return strQ

    def _get_mask_query(self, mask, is_include):
        sub_query = ""
        if mask:
            sub_query += " AND (" if is_include else " AND NOT ("
            is_first = True
            for item in mask.split(","):
                if not is_first:
                    sub_query += " OR "
                sub_query += "(c.table_name LIKE '" + item.strip() + "')"
                is_first = False
            sub_query += ")"
        return sub_query

    def GetFunctionCreatorQuery(self):
        # Runs on Project DB
        strQ = self.ReplaceParms(
            read_template_sql_file(
                f"project_function_creator_{self.flavor}.sql",
                sub_directory=f"flavors/{self.flavor}/setup_profiling_tools",
            )
        )
        return strQ

    def GetProfilingQuery(self):
        # Runs on Project DB
        if not self.dctSnippetTemplate:
            self.dctSnippetTemplate = read_template_yaml_file(
                f"project_profiling_query_{self.flavor}.yaml", sub_directory=f"flavors/{self.flavor}/profiling"
            )

        dctSnippetTemplate = self.dctSnippetTemplate

        # Assemble in function
        strQ = ""

        if self.parm_do_sample == "Y":
            strQ += dctSnippetTemplate["strTemplate01_sampling"]
        else:
            strQ += dctSnippetTemplate["strTemplate01_else"]

        strQ += dctSnippetTemplate["strTemplate02_all"]

        if self.col_gen_type in ["A", "D", "N"]:
            strQ += dctSnippetTemplate["strTemplate03_ADN"]
        else:
            strQ += dctSnippetTemplate["strTemplate03_else"]

        if self.col_gen_type == "A":
            strQ += dctSnippetTemplate["strTemplate04_A"]
        elif self.col_gen_type == "N":
            strQ += dctSnippetTemplate["strTemplate04_N"]
        else:
            strQ += dctSnippetTemplate["strTemplate04_else"]

        if self.col_gen_type == "A":
            strQ += dctSnippetTemplate["strTemplate05_A"]
        else:
            strQ += dctSnippetTemplate["strTemplate05_else"]

        if self.col_gen_type == "A" and self.parm_do_patterns == "Y":
            strQ += dctSnippetTemplate["strTemplate06_A_patterns"]
        else:
            strQ += dctSnippetTemplate["strTemplate06_else"]

        strQ += dctSnippetTemplate["strTemplate07_else"]

        if self.col_gen_type == "N":
            strQ += dctSnippetTemplate["strTemplate08_N"]
        else:
            strQ += dctSnippetTemplate["strTemplate08_else"]

        if self.col_gen_type == "N" and self.col_is_decimal == True:
            strQ += dctSnippetTemplate["strTemplate10_N_dec"]
        else:
            strQ += dctSnippetTemplate["strTemplate10_else"]

        if self.col_gen_type == "D":
            strQ += dctSnippetTemplate["strTemplate11_D"]
        else:
            strQ += dctSnippetTemplate["strTemplate11_else"]
        if self.col_gen_type == "B":
            strQ += dctSnippetTemplate["strTemplate12_B"]
        else:
            strQ += dctSnippetTemplate["strTemplate12_else"]

        strQ += dctSnippetTemplate["strTemplate13_ALL"]

        if self.col_gen_type == "A":
            if self.parm_do_patterns == "Y":
                strQ += dctSnippetTemplate["strTemplate14_A_do_patterns"]
            else:
                strQ += dctSnippetTemplate["strTemplate14_A_no_patterns"]
        else:
            strQ += dctSnippetTemplate["strTemplate14_else"]

        strQ += dctSnippetTemplate["strTemplate15_ALL"]

        strQ += dctSnippetTemplate["strTemplate16_ALL"]

        if self.parm_do_sample == "Y":
            strQ += dctSnippetTemplate["strTemplate98_sampling"]
        else:
            strQ += dctSnippetTemplate["strTemplate98_else"]

        if self.col_gen_type == "N":
            strQ += dctSnippetTemplate["strTemplate99_N"]
        else:
            strQ += dctSnippetTemplate["strTemplate99_else"]

        if self.parm_do_sample == "Y":
            strQ += dctSnippetTemplate["strTemplate100_sampling"]

        strQ = self.ReplaceParms(strQ)

        return strQ

    def GetSecondProfilingQuery(self):
        # Runs on Project DB
        strQ = self.ReplaceParms(
            read_template_sql_file(
                f"project_secondary_profiling_query_{self.flavor}.sql", sub_directory=f"flavors/{self.flavor}/profiling"
            )
        )
        return strQ

    def GetTableSampleCount(self):
        # Runs on Project DB
        strQ = self.ReplaceParms(
            read_template_sql_file("project_get_table_sample_count.sql", sub_directory="profiling")
        )
        return strQ

    def GetContingencyColumns(self):
        # Runs on Project DB
        strQ = self.ReplaceParms(read_template_sql_file("contingency_columns.sql", sub_directory="profiling"))
        return strQ

    def GetContingencyCounts(self):
        # Runs on Project DB
        strQ = self.ReplaceParms(
            read_template_sql_file("contingency_counts.sql", sub_directory="flavors/generic/profiling")
        )
        return strQ

    def UpdateProfileResultsToEst(self):
        # Runs on Project DB
        strQ = self.ReplaceParms(
            read_template_sql_file("project_update_profile_results_to_estimates.sql", sub_directory="profiling")
        )
        return strQ
