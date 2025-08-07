import typing

from testgen.commands.queries.refresh_data_chars_query import CRefreshDataCharsSQL
from testgen.commands.queries.rollup_scores_query import CRollupScoresSQL
from testgen.common import date_service, read_template_sql_file, read_template_yaml_file
from testgen.common.database.database_service import replace_params
from testgen.common.read_file import replace_templated_functions


class CProfilingSQL:
    dctSnippetTemplate: typing.ClassVar = {}

    project_code = ""
    connection_id = ""
    table_groups_id = ""
    flavor = ""
    run_date = ""
    data_schema = ""
    data_table = ""

    col_name = ""
    col_gen_type = ""
    col_type = ""
    col_ordinal_position = "0"
    col_is_decimal = ""
    col_top_freq_update = ""

    parm_table_set = None
    parm_table_include_mask = None
    parm_table_exclude_mask = None
    parm_do_patterns = "Y"
    parm_max_pattern_length = 25
    parm_do_freqs = "Y"
    parm_do_sample = "N"
    parm_sample_size = 0
    profile_run_id = ""
    profile_id_column_mask = ""
    profile_sk_column_mask = ""
    profile_use_sampling = ""
    profile_flag_cdes = False
    profile_sample_percent = ""
    profile_sample_min_count = ""

    sampling_table = ""
    sample_ratio = ""
    sample_percent_calc = ""

    process_id = None

    contingency_max_values = "4"
    contingency_columns = ""

    exception_message = ""

    _data_chars_sql: CRefreshDataCharsSQL = None
    _rollup_scores_sql: CRollupScoresSQL = None

    def __init__(self, strProjectCode, flavor):
        self.flavor = flavor
        self.project_code = strProjectCode
        # Defaults
        self.run_date = date_service.get_now_as_string()
        self.today = date_service.get_now_as_string()

    def _get_data_chars_sql(self) -> CRefreshDataCharsSQL:
        if not self._data_chars_sql:
            params = {
                "project_code": self.project_code,
                "sql_flavor": self.flavor,
                "table_group_schema": self.data_schema,
                "table_groups_id": self.table_groups_id,
                "max_query_chars": None,
                "profiling_table_set": self.parm_table_set,
                "profiling_include_mask": self.parm_table_include_mask,
                "profiling_exclude_mask": self.parm_table_exclude_mask,
            }
            self._data_chars_sql = CRefreshDataCharsSQL(params, self.run_date, "v_latest_profile_results")

        return self._data_chars_sql

    def _get_rollup_scores_sql(self) -> CRollupScoresSQL:
        if not self._rollup_scores_sql:
            self._rollup_scores_sql = CRollupScoresSQL(self.profile_run_id, self.table_groups_id)

        return self._rollup_scores_sql

    def _get_params(self) -> dict:
        return {
            "PROJECT_CODE": self.project_code,
            "CONNECTION_ID": self.connection_id,
            "TABLE_GROUPS_ID": self.table_groups_id,
            "RUN_DATE": self.run_date,
            "DATA_SCHEMA": self.data_schema,
            "DATA_TABLE": self.data_table,
            "COL_NAME": self.col_name,
            "COL_NAME_SANITIZED": self.col_name.replace("'", "''"),
            "COL_GEN_TYPE": self.col_gen_type,
            "COL_TYPE": self.col_type or "",
            "COL_POS": self.col_ordinal_position,
            "TOP_FREQ": self.col_top_freq_update,
            "PROFILE_RUN_ID": self.profile_run_id,
            "PROFILE_ID_COLUMN_MASK": self.profile_id_column_mask,
            "PROFILE_SK_COLUMN_MASK": self.profile_sk_column_mask,
            "START_TIME": self.today,
            "NOW_TIMESTAMP": date_service.get_now_as_string(),
            "EXCEPTION_MESSAGE": self.exception_message,
            "SAMPLING_TABLE": self.sampling_table,
            "SAMPLE_SIZE": int(self.parm_sample_size),
            "PROFILE_USE_SAMPLING": self.profile_use_sampling,
            "PROFILE_SAMPLE_PERCENT": self.profile_sample_percent,
            "PROFILE_SAMPLE_MIN_COUNT": self.profile_sample_min_count,
            "PROFILE_SAMPLE_RATIO": self.sample_ratio,
            "SAMPLE_PERCENT_CALC": self.sample_percent_calc,
            "PARM_MAX_PATTERN_LENGTH": self.parm_max_pattern_length,
            "CONTINGENCY_COLUMNS": self.contingency_columns,
            "CONTINGENCY_MAX_VALUES": self.contingency_max_values,
            "PROCESS_ID": self.process_id,
            "SQL_FLAVOR": self.flavor,
        }

    def _get_query(
        self,
        template_file_name: str,
        sub_directory: str | None = "profiling",
        extra_params: dict | None = None,
    ) -> tuple[str | None, dict]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = {}

        if query:
            if extra_params:
                params.update(extra_params)
            params.update(self._get_params())

            query = replace_params(query, params)
            query = replace_templated_functions(query, self.flavor)

        return query, params

    def GetSecondProfilingColumnsQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("secondary_profiling_columns.sql")

    def GetSecondProfilingUpdateQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("secondary_profiling_update.sql")

    def GetSecondProfilingStageDeleteQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("secondary_profiling_delete.sql")

    def GetDataTypeSuggestionUpdateQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("datatype_suggestions.sql")

    def GetFunctionalDataTypeUpdateQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("functional_datatype.sql")

    def GetFunctionalTableTypeStageQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("functional_tabletype_stage.sql")

    def GetFunctionalTableTypeUpdateQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("functional_tabletype_update.sql")

    def GetPIIFlagUpdateQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("pii_flag.sql")

    def GetAnomalyStatsRefreshQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("refresh_anomalies.sql")

    def GetAnomalyScoringRollupRunQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_rollup_scores_sql().GetRollupScoresProfileRunQuery()

    def GetAnomalyScoringRollupTableGroupQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_rollup_scores_sql().GetRollupScoresProfileTableGroupQuery()

    def GetAnomalyTestTypesQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("profile_anomaly_types_get.sql")

    def GetAnomalyTestQuery(self, test_type: dict) -> tuple[str, dict] | None:
        # Runs on App database
        extra_params = {
            "ANOMALY_ID": test_type["id"],
            "DETAIL_EXPRESSION": test_type["detail_expression"],
            "ANOMALY_CRITERIA": test_type["anomaly_criteria"],
        }

        match test_type["data_object"]:
            case "Column":
                query, params = self._get_query("profile_anomalies_screen_column.sql", extra_params=extra_params)
            case "Multi-Col":
                query, params = self._get_query("profile_anomalies_screen_multi_column.sql", extra_params=extra_params)
            case "Dates":
                query, params = self._get_query("profile_anomalies_screen_table_dates.sql", extra_params=extra_params)
            case "Table":
                query, params = self._get_query("profile_anomalies_screen_table.sql", extra_params=extra_params)
            case "Variant":
                query, params = self._get_query("profile_anomalies_screen_variants.sql", extra_params=extra_params)
            case _:
                return None

        return query, params

    def GetAnomalyScoringQuery(self, test_type: dict) -> tuple[str, dict]:
        # Runs on App database
        query = read_template_sql_file("profile_anomaly_scoring.sql", sub_directory="profiling")
        params = {
            "PROFILE_RUN_ID": self.profile_run_id,
            "ANOMALY_ID": test_type["id"],
            "PREV_FORMULA": test_type["dq_score_prevalence_formula"],
            "RISK": test_type["dq_score_risk_factor"],
        }
        query = replace_params(query, params)
        return query, params

    def GetDataCharsRefreshQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_data_chars_sql().GetDataCharsUpdateQuery()

    def GetCDEFlaggerQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("cde_flagger_query.sql")

    def GetProfileRunInfoRecordsQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("project_profile_run_record_insert.sql")

    def GetProfileRunInfoRecordUpdateQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("project_profile_run_record_update.sql")

    def GetDDFQuery(self) -> tuple[str, dict]:
        # Runs on Target database
        return self._get_data_chars_sql().GetDDFQuery()

    def GetProfilingQuery(self) -> tuple[str, dict]:
        # Runs on Target database
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
            if self.parm_do_sample == "Y":
                strQ += dctSnippetTemplate["strTemplate99_N_sampling"]
            else:
                strQ += dctSnippetTemplate["strTemplate99_N"]
        else:
            strQ += dctSnippetTemplate["strTemplate99_else"]

        if self.parm_do_sample == "Y":
            strQ += dctSnippetTemplate["strTemplate100_sampling"]

        params = self._get_params()
        query = replace_params(strQ, params)
        query = replace_templated_functions(query, self.flavor)

        return query, params

    def GetSecondProfilingQuery(self) -> tuple[str, dict]:
        # Runs on Target database
        return self._get_query(f"project_secondary_profiling_query_{self.flavor}.sql", f"flavors/{self.flavor}/profiling")

    def GetTableSampleCount(self) -> tuple[str, dict]:
        # Runs on Target database
        return self._get_query(f"project_get_table_sample_count_{self.flavor}.sql", f"flavors/{self.flavor}/profiling")

    def GetContingencyColumns(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("contingency_columns.sql")

    def GetContingencyCounts(self) -> tuple[str, dict]:
        # Runs on Target database
        return self._get_query("contingency_counts.sql", "flavors/generic/profiling")

    def UpdateProfileResultsToEst(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("project_update_profile_results_to_estimates.sql")
